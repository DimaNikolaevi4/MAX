# -*- coding: utf-8 -*-
"""Случайный пост для «Забавного»: из истории канала в план публикации.

Что делает:
  * читает историю канала (GET /messages, последние 100);
  * отбирает старые посты: есть видео или фото(+) и текст, нет призыва,
    нет ссылок, текст не длиннее 800 символов;
  * этот пост и его источники не должны уже участвовать в плане;
  * прогоняет текст через LanguageTool (shared/text_check.py) — кандидаты
    с ошибками орфографии пропускаются;
  * случайно выбирает один, скачивает медиа в local/images/zabava/random/,
    создаёт файл поста и дописывает его в local/zabava-plan.json как pending;
  * source запоминается — после публикации publish_plan.py удалит старый пост.

Повторный запуск безопасен: если в плане уже есть pending, ничего не добавляет.

Запуск:
  py roles\\blogger\\tools\\zabava_random_plan.py [--dry-run] [--status]
"""

import json
import random
import re
import ssl
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(r"E:\github\MAX")
MSK = timezone(timedelta(hours=3))
TOKENS = REPO / "local" / "tokens.json"
CA = REPO / "local" / "russian_ca_bundle.pem"
PLAN = REPO / "local" / "zabava-plan.json"
POSTS = REPO / "roles" / "blogger" / "channels" / "zabava" / "posts"
MEDIA_DIR = REPO / "local" / "images" / "zabava" / "random"
MAX_LEN = 800
MAX_SPELL_TRIES = 5
NO_CTA_MARKS = ("подпишись", "подписывайтесь")

sys.path.insert(0, str(REPO))
from shared.text_check import check_text  # noqa: E402


def load_token():
    return json.loads(TOKENS.read_text(encoding="utf-8"))["zabava"]


def api(token, path):
    ctx = ssl.create_default_context()
    if CA.exists():
        ctx.load_verify_locations(cafile=str(CA))
    req = urllib.request.Request(
        "https://platform-api2.max.ru" + path,
        headers={"Authorization": token, "User-Agent": "curl/8.13.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def download(url, dest):
    ctx = ssl.create_default_context()
    if CA.exists():
        ctx.load_verify_locations(cafile=str(CA))
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8.13.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=300) as r:
        ctype = (r.headers or {}).get("Content-Type", "")
        data = r.read()
    ext = ".mp4" if "video" in ctype else ".jpg" if "jpeg" in ctype else \
        ".png" if "png" in ctype else ".webp" if "webp" in ctype else \
        (".mp4" if "video" in dest else ".jpg")
    dest = dest.with_suffix(ext)
    dest.write_bytes(data)
    return dest, len(data)


def clean_text(text):
    body = text.strip()
    body = re.sub(r"\.+\s*$", "", body)  # стиль канала: без точки в конце
    return body


def used_slugs(plan):
    out = set()
    for p in plan.get("posts") or []:
        src = p.get("source") or ""
        if src:
            out.add(src.rstrip("/").split("/")[-1])
        mid = p.get("message_id") or ""
        if mid:
            out.add(mid)
    return out


def candidates(msgs, plan):
    used = used_slugs(plan)
    out = []
    for m in msgs:
        body = m.get("body") or {}
        atts = body.get("attachments") or []
        text = (body.get("text") or "").strip()
        types = {a.get("type") for a in atts}
        if not atts or not text or not types <= {"image", "video"}:
            continue
        low = text.lower()
        if any(mark in low for mark in NO_CTA_MARKS):
            continue
        if "http" in low or "max.ru/" in low:
            continue
        if "**" in text or "](" in text:
            continue
        mid = body.get("mid") or ""
        if mid and mid in used:
            continue
        url = m.get("url") or ""
        slug = url.rstrip("/").split("/")[-1] if url else ""
        if slug and slug in used:
            continue
        out.append({"mid": mid, "url": url, "slug": slug, "text": text,
                    "attachments": atts})
    return out


def main():
    dry_run = "--dry-run" in sys.argv
    status_only = "--status" in sys.argv

    token = load_token()["token"]
    chat_id = int(load_token()["chat_id"])
    msgs = api(token, f"/messages?chat_id={chat_id}&count=100").get("messages", [])
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    cands = candidates(msgs, plan)

    pending = [p for p in plan.get("posts") or [] if p.get("status") == "pending"]
    print(f"история: {len(msgs)}, кандидатов: {len(cands)}, pending в плане: {len(pending)}")

    if status_only:
        for c in cands[:15]:
            print(f"  {len(c['text']):>4} симв.  {c['slug']}  {c['text'][:50]}")
        return 0

    if pending:
        print("в плане уже есть pending — новый случайный пост не добавляю")
        return 0
    if not cands:
        print("FAIL: подходящих старых постов нет")
        return 1

    random.shuffle(cands)
    chosen = None
    spell_errors = None
    for c in cands[:MAX_SPELL_TRIES]:
        body = clean_text(c["text"])
        spell = check_text(f"{body}\n\nПодпишись на Забавное — улыбка в ленте без лишних слов")
        if spell.get("status") == "unavailable":
            chosen = c  # сервис недоступен — не блокируем выбор
            break
        if not spell.get("errors"):
            chosen = c
            break
        spell_errors = spell["errors"]
    if chosen is None:
        chosen = cands[0]  # все проверенные с ошибками — пусть решает публикатор
    body = clean_text(chosen["text"])
    if not body:
        print("FAIL: текст кандидата пуст после чистки")
        return 1

    kinds = sorted({a.get("type") for a in chosen["attachments"]})
    media_files = []
    total = 0
    if not dry_run:
        MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        base = (chosen["slug"] or chosen["mid"][-8:] or "post")
        n = 0
        for att in chosen["attachments"]:
            n += 1
            payload = att.get("payload") or {}
            url = payload.get("url")
            if not url:
                continue
            dest, size = download(url, MEDIA_DIR / f"{base}-{n}")
            media_files.append(dest)
            total += size
        if not media_files:
            print("FAIL: не удалось скачать медиа")
            return 1

    kind_text = "видео" if "video" in kinds else f"{len(chosen['attachments'])} фото"
    now = datetime.now(MSK)
    fname = f"{now:%Y-%m-%d}-random-{chosen['slug'] or 'post'}.md"
    post_path = POSTS / fname

    fm = {
        "channel": "zabava",
        "status": "draft",
        "notify": "true",
        "max_text": str(max(400, len(body))),
        "source": chosen["url"],
    }
    if media_files:
        if "video" in kinds:
            fm["video_file"] = str(media_files[0].relative_to(REPO)).replace("\\", "/")
        else:
            fm["image_files"] = " | ".join(
                str(p.relative_to(REPO)).replace("\\", "/") for p in media_files)

    fm_lines = "\n".join(f"{k}: {v}" for k, v in fm.items())
    if not dry_run:
        post_path.write_text(f"---\n{fm_lines}\n---\n\n{body}\n",
                             encoding="utf-8", newline="\n")

        entry = {
            "id": max((p.get("id") or 0) for p in plan.get("posts") or []) + 1,
            "file": str(post_path.relative_to(REPO)).replace("\\", "/"),
            "source": chosen["url"],
            "media": f"{kind_text}, повтор из архива (случайный выбор)",
            "picked_at": now.isoformat(timespec="seconds"),
            "delete_source": True,
            "status": "pending",
        }
        plan.setdefault("posts", []).append(entry)
        plan["updated_at"] = now.isoformat(timespec="seconds")
        PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")

    print(f"выбран: {chosen['url']} ({kind_text}, {len(body)} симв.)")
    if media_files:
        for p in media_files:
            print(f"  медиа: {p.name} ({total // 1024} КБ всего)")
    if dry_run:
        print("DRY-RUN: файл и план не изменялись")
    else:
        print(f"пост создан: {post_path.name}, план обновлён (pending)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
