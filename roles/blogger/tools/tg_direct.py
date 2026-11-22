# -*- coding: utf-8 -*-
"""Резервная публикация в Telegram напрямую через api.telegram.org.

Используется, когда релей 0s3.ru недоступен: api.telegram.org открывается
по конкретному IP через --resolve. Логика разметки и записи архива — как в
roles/blogger/tools/publish_telegram.py.

Профиль telegram, только status: approved, hold блокирует публикацию;
реакции — по общему интервалу (roles/blogger/config/reactions-registry.json).
Перед отправкой вызывается shared/format_core.py — второй копии правил нет.
Неизвестные поля front matter сохраняются при перезаписи архива.
Новый пост ядра создаётся с полем format_core: 1; telegram-профиль живёт
по своему канону (roles/blogger/channels/tg_neuro/style.md) и это поле не ставит.

    python roles/blogger/tools/tg_direct.py roles/blogger/channels/tg_neuro/posts/<файл>.md --ip 149.154.167.220
"""
import argparse
import importlib.util
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / ".git").exists())))
from shared.paths import REPO, CONFIG, ensure_publish_allowed  # noqa: E402
from shared import format_core  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "pt", Path(__file__).resolve().parent / "publish_telegram.py")
pt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pt)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("post")
    ap.add_argument("--ip", default="149.154.167.220")
    a = ap.parse_args()

    path = Path(a.post)
    if not path.is_absolute():
        path = REPO / path
    report = []
    fm, body = format_core.split_post(path.read_text(encoding="utf-8"))
    body = body.strip()
    channel = fm.get("channel") or "tg_neuro"
    status = (fm.get("status") or "").strip().lower()
    if status != "approved":
        raise SystemExit(f"статус {status or 'не задан'!r}: публикация возможна только из approved")
    if fm.get("hold"):
        raise SystemExit("пост на паузе (hold) — снятие только по команде владельца")

    tok = json.loads((REPO / "local" / "tokens.json").read_text(encoding="utf-8"))["tg_neuro"]
    chat_id, token = tok["chat_id"], tok["token"]
    cfg = json.loads((CONFIG / "channels.json").read_text(encoding="utf-8"))
    ch = next((c for c in cfg["channels"] if c["slug"] == channel), None)
    if not ch or format_core.profile_of(ch) != "telegram":
        raise SystemExit(f"канал {channel!r} не имеет профиль telegram")
    ensure_publish_allowed(channel, tool="tg_direct")
    cta = format_core.resolve_cta(channel, fm, ch)
    cta_url = cta["url"]

    core_result = format_core.check_post(
        path, channel=channel, fm=fm, text=body,
        for_publish=True, check_spellcheck=False)
    for issue in core_result.issues:
        report.append(str(issue))
    if not core_result.ok:
        (REPO / "local" / f"publish-{channel}.txt").write_text(
            "\n".join(report), encoding="utf-8")
        raise SystemExit("format_core: " + "; ".join(i.message for i in core_result.errors))

    html = pt.md_to_html(body)
    btn = json.dumps({"inline_keyboard": [[{"text": "Перейти в канал", "url": cta_url}]]}, ensure_ascii=False)

    cap_f = REPO / "local" / "tg-caption.html"
    btn_f = REPO / "local" / "tg-button.json"
    cap_f.write_text(html, encoding="utf-8")
    btn_f.write_text(btn, encoding="utf-8")

    img = REPO / fm["image_file"]
    cmd = ["curl.exe", "-s", "-X", "POST",
           "--resolve", f"api.telegram.org:443:{a.ip}",
           "-F", f"chat_id={chat_id}",
           "-F", "parse_mode=HTML",
           "-F", f"caption=<{cap_f}",
           "-F", f"reply_markup=<{btn_f}",
           "-F", f"photo=@{img};type=image/png",
           f"https://api.telegram.org/bot{token}/sendPhoto"]
    r = subprocess.run(cmd, capture_output=True)
    txt = (r.stdout or b"").decode("utf-8", errors="replace")
    try:
        resp = json.loads(txt)
    except json.JSONDecodeError:
        raise SystemExit(f"не JSON: {txt[:300]}")

    if not resp.get("ok"):
        report.append(f"FAIL: Telegram отклонил: {json.dumps(resp, ensure_ascii=False)[:300]}")
        (REPO / "local" / "publish-tg_neuro.txt").write_text("\n".join(report), encoding="utf-8")
        raise SystemExit("FAIL")

    res = resp["result"]
    mid = res["message_id"]
    checks = {
        "message_id получен": bool(mid),
        "разметка применилась": len(res.get("caption_entities") or []) > 0,
        "фото прикрепилось": "photo" in res,
        "кнопка на месте": any(
            b.get("url") == cta_url
            for row in (res.get("reply_markup", {}) or {}).get("inline_keyboard", [])
            for b in row),
        "подпись <=1024": len(html) <= 1024,
    }
    for k, v in checks.items():
        report.append(f"{'PASS' if v else 'FAIL'}: {k}")

    now = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%dT%H:%M:%S+03:00")
    fm_out = {"channel": channel, "status": "published", "format": "html",
              "published_at": now, "message_id": str(mid), "chat_id": chat_id}
    fm.update(fm_out)  # round-trip front matter
    path.write_text(fm.render() + ("\n" if not body.startswith("\n") else "") + body,
                    encoding="utf-8", newline="\n")
    report.append(f"OK: {path.name} -> message_id {mid} (напрямую через api.telegram.org/{a.ip}; релей 0s3.ru недоступен)")
    (REPO / "local" / "publish-tg_neuro.txt").write_text("\n".join(report), encoding="utf-8")
    print("ok")


if __name__ == "__main__":
    main()

