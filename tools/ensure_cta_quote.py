# -*- coding: utf-8 -*-
"""Правка старых постов: привести нижний блок к цитате-призыву (CTA) с ссылкой
на канал + применить текстовые исправления из файла-задания.

Использование:
  python tools/ensure_cta_quote.py <post.md> [<post2.md> ...] [--dry-run]

Файлы задания (необязательные): local/fix-<slug>.json
  {"replacements": [["старый точный текст", "новый текст"], ...]}
Каждая замена должна встречаться ровно 1 раз, иначе пост пропускается.

Фразы CTA: local/cta-assignments.json — {"<имя файла поста>": "фраза"}.
Отчёт: local/cta-batch-report.txt (UTF-8).
"""
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(r"E:\github\MAX")
TOKEN = json.loads((REPO / "local" / "tokens.json").read_text(encoding="utf-8"))
# токен бота ainow лежит под ключом канала
AINOW = TOKEN.get("ainow") or TOKEN
TOKEN_STR = AINOW.get("token") if isinstance(AINOW, dict) else None
if not TOKEN_STR:
    raise SystemExit("не нашёл токен в local/tokens.json")
API = "https://platform-api2.max.ru"
CTA_URL = "https://max.ru/channel_ainow"
REPORT = []

DRY = "--dry-run" in sys.argv
POSTS = [a for a in sys.argv[1:] if not a.startswith("--")]


def api(method: str, url: str, payload_path: Path | None = None, out: Path | None = None) -> int:
    cmd = ["curl.exe", "-s", "-X", method, "-H", f"Authorization: {TOKEN_STR}"]
    if payload_path:
        cmd += ["-H", "Content-Type: application/json", "--data-binary", f"@{payload_path}"]
    cmd.append(f"{API}{url}")
    if out:
        cmd += ["-o", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode


def utf16_to_cp_map(text: str):
    prefix = [0]
    for ch in text:
        prefix.append(prefix[-1] + (2 if ord(ch) > 0xFFFF else 1))
    return prefix


def cp_at(prefix, u16):
    lo, hi = 0, len(prefix) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if prefix[mid] <= u16:
            lo = mid
        else:
            hi = mid - 1
    return lo


def build_markdown(text: str, markup: list) -> str:
    prefix = utf16_to_cp_map(text)
    items = []
    for m in markup or []:
        items.append({"from": cp_at(prefix, m["from"]), "to": cp_at(prefix, m["from"] + m["length"]),
                      "type": m["type"], "url": m.get("url")})
    items.sort(key=lambda it: (it["from"], -(it["to"] - it["from"])))
    groups = []
    for it in items:
        if groups and it["from"] < groups[-1][-1]["to"]:
            groups[-1].append(it)
        else:
            groups.append([it])
    out, pos = [], 0
    for g in groups:
        s, e = g[0]["from"], g[0]["to"]
        frag = text[s:e]
        has_link = any(x["type"] == "link" for x in g)
        has_strong = any(x["type"] == "strong" for x in g)
        url = next((x["url"] for x in g if x["type"] == "link"), None)
        inner = f"[{frag}]({url})" if has_link else frag
        out.append(text[pos:s])
        out.append(f"**{inner}**" if has_strong else inner)
        pos = e
    out.append(text[pos:])
    return "".join(out)


cta_assign = json.loads((REPO / "local" / "cta-assignments.json").read_text(encoding="utf-8"))

for post_path in POSTS:
    p = Path(post_path)
    if not p.is_absolute():
        p = REPO / p
    name = p.name
    slug = p.stem
    try:
        raw = p.read_text(encoding="utf-8")
        fm = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n?", raw, re.S).group(1)
        mid_m = re.search(r"message_id:\s*(\S+)", fm)
        if not mid_m:
            raise ValueError("нет message_id в front matter")
        mid = mid_m.group(1)

        # 1. GET текущего состояния
        get_json = REPO / "local" / "cta-get.json"
        if api("GET", f"/messages/{mid}", out=get_json) != 0:
            raise ValueError("GET failed (curl)")
        d = json.loads(get_json.read_text(encoding="utf-8"))
        body = d["body"]
        text, markup = body["text"], body.get("markup") or []
        atts_before = len(body.get("attachments") or [])
        md = build_markdown(text, markup)

        # 2. CTA-трансформация (построчно: у старых постов CTA приклеен к
        #    предыдущему абзацу одиночным \n — блок целиком заменять нельзя)
        reason = cta_assign.get(name)
        if not reason:
            raise ValueError("нет фразы CTA в cta-assignments.json")
        cta_line = f"> **Подписывайтесь на [AI]({CTA_URL})** — {reason}"
        lines = md.split("\n")
        cta_lines = [i for i, ln in enumerate(lines) if "Подписывайтесь" in ln]
        if len(cta_lines) > 1:
            raise ValueError(f"строк с 'Подписывайтесь' несколько: {cta_lines}")
        if cta_lines:
            old_line = lines[cta_lines[0]].strip()
            changed_cta = f"CTA заменён (был: {old_line[:70]!r})"
            lines.pop(cta_lines[0])
            # сироты-хвосты: оторванные знаки и пустые строки после CTA
            JUNK = {"", ".", "!", "—", "–", "-", "🚀", "👇"}
            while lines and lines[-1].strip() in JUNK:
                lines.pop()
        else:
            changed_cta = "CTA добавлен (не было строки призыва)"
        md = "\n".join(lines).rstrip("\n") + "\n\n" + cta_line + "\n"
        blocks = md.split("\n\n")

        if "--dump-md" in sys.argv:
            (REPO / "local" / f"md-{slug}.txt").write_text("\n\n".join(blocks), encoding="utf-8")
            REPORT.append(f"[DUMP] {name}: md сохранён")
            continue

        # 3. Текстовые замены (если есть файл задания)
        fix_file = REPO / "local" / f"fix-{slug}.json"
        applied_fixes = []
        if fix_file.exists():
            fixes = json.loads(fix_file.read_text(encoding="utf-8"))["replacements"]
            joined = "\n\n".join(blocks)
            for old, new in fixes:
                n = joined.count(old)
                if n != 1:
                    (REPO / "local" / f"md-{slug}.txt").write_text(joined, encoding="utf-8")
                    raise ValueError(f"замена {old[:40]!r}: вхождений {n}, нужно 1 (md в local/md-{slug}.txt)")
                joined = joined.replace(old, new)
                applied_fixes.append(old[:40])
            blocks = joined.split("\n\n")

        final_md = "\n\n".join(blocks).strip() + "\n"
        if len(final_md) > 4000:
            raise ValueError(f"длина {len(final_md)} > 4000")

        # 4. PUT
        put_json = REPO / "local" / "cta-put.json"
        put_json.write_text(json.dumps({"text": final_md.rstrip("\n"), "format": "markdown"},
                                       ensure_ascii=False), encoding="utf-8")
        if DRY:
            REPORT.append(f"[DRY] {name}: {changed_cta}; правки: {len(applied_fixes)}; длина {len(final_md)}")
            continue
        time.sleep(0.6)
        if api("PUT", f"/messages?message_id={mid}", payload_path=put_json) != 0:
            raise ValueError("PUT failed (curl)")

        # 5. GET-проверка
        time.sleep(0.6)
        if api("GET", f"/messages/{mid}", out=get_json) != 0:
            raise ValueError("GET after PUT failed")
        b2 = json.loads(get_json.read_text(encoding="utf-8"))["body"]
        t2 = b2["text"]
        checks = {
            "CTA в тексте": "Подписывайтесь на AI" in t2[-200:],
            "нет '>' в тексте": ">" not in t2,
            "ссылка канала в разметке": any(m.get("url") == CTA_URL for m in (b2.get("markup") or [])),
            "вложение сохранено": len(b2.get("attachments") or []) == atts_before,
            "длина ≤4000": len(t2) <= 4000,
        }
        if not all(checks.values()):
            bad = [k for k, v in checks.items() if not v]
            raise ValueError(f"проверка FAIL: {bad}")

        # 6. Архив
        edited_at = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%dT%H:%M:%S+03:00")
        if "edited_at:" in fm:
            fm = re.sub(r"edited_at:.*", f"edited_at: {edited_at}", fm)
        else:
            fm += f"\nedited_at: {edited_at}"
        p.write_text(f"---\n{fm}\n---\n\n{final_md}", encoding="utf-8", newline="\n")
        REPORT.append(f"OK {name}: {changed_cta}; правки: {applied_fixes or 'нет'}; "
                      f"текст {len(t2)} симв., разметка {len(b2.get('markup') or [])}, вложения {atts_before}")
    except Exception as e:
        REPORT.append(f"FAIL {name}: {e}")

(REPO / "local" / "cta-batch-report.txt").write_text("\n".join(REPORT), encoding="utf-8")
print(f"done: {len(REPORT)} записей")
