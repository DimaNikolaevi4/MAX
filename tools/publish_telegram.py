# -*- coding: utf-8 -*-
"""Публикация поста в Telegram-канал через релей на хостинге.

Использование:
  python tools/publish_telegram.py [--channel <slug>] <post.md>

Отличия от MAX (tools/publish_post.py):
- транспорт: POST на релей (deploy/tg-relay.php) на хостинге пользователя,
  т.к. api.telegram.org из локальной среды недоступен (блокировка провайдера);
- разметка: markdown конвертируется в HTML (**жирный**, [текст](ссылка));
- под каждым постом — inline-кнопка (button_url из front matter или
  cta_url канала);
- проверка: ответ Telegram содержит result.message_id, entities и caption —
  это и есть контроль публикации.

Запись в local/tokens.json для telegram-канала:
  "<slug>": {
    "relay_url": "https://<домен>/tg-relay.php",
    "secret": "<секрет из tg-config.php на хостинге>",
    "chat_id": "@username_канала",
    "review_chat_id": 537566305
  }

Front matter поста: channel, status: draft, image_file (карточка),
button_url (необязательно; по умолчанию cta_url канала), pin (true для
первого поста). После публикации дописываются: status: published,
published_at, message_id.
"""
import json
import re
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REPORT = []


def md_to_html(text: str) -> str:
    # сначала экранируем HTML-спецсимволы, затем восстанавливаем разметку
    t = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2">\1</a>', t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<i>\1</i>", t)
    return t


def main() -> None:
    args = sys.argv[1:]
    channel = None
    if "--channel" in args:
        i = args.index("--channel")
        channel = args[i + 1]
        del args[i:i + 2]
    post_path = Path(args[0])
    if not post_path.is_absolute():
        post_path = REPO / post_path

    raw = post_path.read_text(encoding="utf-8")
    m = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n?(.*)", raw, re.S)
    fm_text, body = m.group(1), m.group(2).strip()
    fm = {}
    for line in fm_text.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    channel = channel or fm.get("channel")
    if not channel:
        raise SystemExit("не определён канал (front matter channel или --channel)")

    tokens = json.loads((REPO / "local" / "tokens.json").read_text(encoding="utf-8"))
    entry = tokens.get(channel, {})
    relay_url, secret = entry.get("relay_url"), entry.get("secret")
    chat_id = entry.get("chat_id")
    if not (relay_url and secret and chat_id):
        raise SystemExit(f"в local/tokens.json[{channel!r}] нет relay_url/secret/chat_id")

    cfg = json.loads((REPO / "config" / "channels.json").read_text(encoding="utf-8"))
    ch = next((c for c in cfg["channels"] if c["slug"] == channel), None)
    cta_url = (ch or {}).get("cta_url") or fm.get("button_url")
    if not cta_url:
        raise SystemExit("нет cta_url канала и button_url в front matter")

    html = md_to_html(body)
    if len(html) > 1024 and not fm.get("image_file"):
        REPORT.append(f"ВНИМАНИЕ: текст {len(html)} симв. > 1024 (лимит caption Telegram)")
    if len(html) > 4096:
        raise SystemExit(f"текст {len(html)} > 4096 (лимит sendMessage)")

    # multipart-запрос к релею
    boundary = "----MAXRELAY" + uuid.uuid4().hex
    parts = []

    def field(name: str, value: str) -> None:
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode("utf-8"))

    field("secret", secret)
    field("chat_id", chat_id)
    field("text", html)
    field("button_url", fm.get("button_url", cta_url))
    field("button_text", fm.get("button_text", "Перейти в канал"))
    if fm.get("pin") == "true":
        field("pin", "1")

    image_file = fm.get("image_file")
    if image_file:
        img = (REPO / image_file).read_bytes()
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo_file\"; filename=\"card.png\"\r\n"
            f"Content-Type: image/png\r\n\r\n".encode("utf-8") + img + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    payload = b"".join(parts)

    tmp = REPO / "local" / f"tg-payload-{channel}.bin"
    tmp.write_bytes(payload)

    r = subprocess.run(["curl.exe", "-s", "-X", "POST",
                        "-H", f"Content-Type: multipart/form-data; boundary={boundary}",
                        "--data-binary", f"@{tmp}",
                        "-w", "\nHTTP:%{http_code}",
                        relay_url], capture_output=True)
    resp_text = (r.stdout or b"").decode("utf-8", errors="replace")
    body_resp, _, http_code = resp_text.rpartition("HTTP:")
    try:
        resp = json.loads(body_resp)
    except json.JSONDecodeError:
        raise SystemExit(f"релей вернул не JSON (HTTP {http_code.strip()}): {resp_text[:300]}")

    if not resp.get("ok"):
        REPORT.append(f"FAIL: Telegram отклонил: {json.dumps(resp, ensure_ascii=False)[:300]}")
        raise SystemExit("публикация FAIL, см. отчёт")

    result = resp["result"]
    mid = result.get("message_id")
    ents = result.get("caption_entities") or result.get("entities") or []
    checks = {
        "message_id получен": bool(mid),
        "разметка применилась": len(ents) > 0,
        "фото прикрепилось": ("photo" in result) if image_file else True,
        "кнопка на месте": any(
            b.get("url") == fm.get("button_url", cta_url)
            for row in (result.get("reply_markup", {}) or {}).get("inline_keyboard", [])
            for b in row) or not image_file and not fm.get("button_url") and cta_url == fm.get("button_url", cta_url),
    }
    for k, v in checks.items():
        REPORT.append(f"{'PASS' if v else 'FAIL'}: {k}")

    now = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%dT%H:%M:%S+03:00")
    fm_out = {"channel": channel, "status": "published", "format": "html",
              "published_at": now, "message_id": str(mid), "chat_id": chat_id}
    fm_lines = "\n".join(f"{k}: {v}" for k, v in fm_out.items())
    post_path.write_text(f"---\n{fm_lines}\n---\n\n{body}\n", encoding="utf-8", newline="\n")

    REPORT.append(f"OK: {post_path.name} -> message_id {mid}")
    (REPO / "local" / f"publish-{channel}.txt").write_text("\n".join(REPORT), encoding="utf-8")
    print("ok")


if __name__ == "__main__":
    main()
