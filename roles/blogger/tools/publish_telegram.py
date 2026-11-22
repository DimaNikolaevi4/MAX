# -*- coding: utf-8 -*-
"""Публикация поста в Telegram-канал через релей на хостинге.

Использование:
  python roles/blogger/tools/publish_telegram.py [--channel <slug>] <post.md>

Отличия от MAX (roles/blogger/tools/publish_post.py):
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
    "chat_id": "@username_канала"
  }

Front matter поста: channel, status: approved, image_file (карточка),
button_url (необязательно; по умолчанию cta_url канала), pin (true для
первого поста), hold (пауза — публикация запрещена). После публикации
дописываются: status: published, published_at, message_id. Все неизвестные
поля front matter сохраняются (format_core round-trip).

Профиль — telegram (roles/blogger/channels/tg_neuro/style.md): подпись ≤1000, жирный
заголовок с эмодзи, ≥1 ссылка на пост ainow, CTA последней строкой без '> '
с inline-кнопкой, реакции по общему интервалу. Новый пост ядра оформляется
с format_core: 1; telegram-профиль живёт по своему канону.
Проверка текста — через shared/format_core.py, без вторых копий правил.
"""
import json
import re
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / ".git").exists())))
from shared.paths import REPO, CONFIG, ensure_publish_allowed  # noqa: E402
from shared import format_core  # noqa: E402
REPORT = []


def flush_report(channel: str) -> None:
    (REPO / "local" / f"publish-{channel}.txt").write_text(
        "\n".join(REPORT), encoding="utf-8")


def fail(message: str, channel: str) -> None:
    REPORT.append("FAIL: " + message)
    flush_report(channel)
    raise SystemExit(message)


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

    fm, body = format_core.split_post(post_path.read_text(encoding="utf-8"))
    body = body.strip()
    channel = channel or fm.get("channel")
    if not channel:
        fail("не определён канал (front matter channel или --channel)", "tg_neuro")
    if fm.get("hold"):
        fail("пост на паузе до команды владельца: " + str(fm["hold"]), channel)

    tokens = json.loads((REPO / "local" / "tokens.json").read_text(encoding="utf-8"))
    entry = tokens.get(channel, {})
    relay_url, secret = entry.get("relay_url"), entry.get("secret")
    chat_id = entry.get("chat_id")
    if not (relay_url and secret and chat_id):
        raise SystemExit(f"в local/tokens.json[{channel!r}] нет relay_url/secret/chat_id")

    cfg = json.loads((CONFIG / "channels.json").read_text(encoding="utf-8"))
    ch = next((c for c in cfg["channels"] if c["slug"] == channel), None)
    ensure_publish_allowed(channel, tool="publish_telegram")
    if not ch:
        fail(f"канал {channel!r} не найден в channels.json", channel)
    if format_core.profile_of(ch) != "telegram":
        fail(f"канал {channel!r} не имеет профиль telegram", channel)
    status = (fm.get("status") or "").strip().lower()
    if status != "approved":
        fail(f"статус {status or 'не задан'!r}: публикация возможна только из approved", channel)

    cta = format_core.resolve_cta(channel, fm, ch)
    cta_url = cta["url"] or fm.get("button_url")
    if not cta_url:
        fail("нет cta_url канала и button_url в front matter", channel)

    # --- единый движок формата (профиль telegram, реакции, CTA и т.д.) ---
    core_result = format_core.check_post(
        post_path, channel=channel, fm=fm, text=body,
        for_publish=True, check_spellcheck=False)
    for issue in core_result.issues:
        REPORT.append(str(issue))
    if not core_result.ok:
        fail("format_core: " + "; ".join(i.message for i in core_result.errors), channel)

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
        REPORT.append(f"FAIL: релей вернул не JSON (HTTP {http_code.strip()}): "
                      f"{resp_text[:300]}")
        (REPO / "local" / f"publish-{channel}.txt").write_text(
            "\n".join(REPORT), encoding="utf-8")
        raise SystemExit("релей вернул не JSON, см. отчёт")

    if not resp.get("ok"):
        REPORT.append(f"FAIL: Telegram отклонил: {json.dumps(resp, ensure_ascii=False)[:300]}")
        (REPO / "local" / f"publish-{channel}.txt").write_text(
            "\n".join(REPORT), encoding="utf-8")
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
    fm.update(fm_out)  # round-trip: неизвестные поля и порядок сохраняются
    post_path.write_text(fm.render() + ("\n" if not body.startswith("\n") else "") + body,
                         encoding="utf-8", newline="\n")

    REPORT.append(f"OK: {post_path.name} -> message_id {mid}")
    (REPO / "local" / f"publish-{channel}.txt").write_text("\n".join(REPORT), encoding="utf-8")
    print("ok")


if __name__ == "__main__":
    main()
