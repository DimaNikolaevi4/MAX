# -*- coding: utf-8 -*-
"""Публикация поста в канал MAX (параметризовано по каналу).

Использование:
  python tools/publish_post.py [--channel ainow] <post.md>

Транспорт (раздел 5 AGENTS.md, TLS-проблемы 06.11):
  $env:MAX_HTTP='python'                          # весь HTTP на stdlib urllib
  $env:MAX_CA_CERT=local/russian_ca_bundle.pem    # доверие += бандл Минцифры
  По умолчанию HTTP идёт через curl.exe (--cacert, если MAX_CA_CERT задан);
  schannel не принимает российскую цепочку iu.oneme.ru даже с --cacert,
  поэтому для загрузки обложки на Windows использовать MAX_HTTP=python.

Файл поста: front matter + тело (Markdown). Обязательные поля front matter:
  channel: <slug>            — должен совпадать с --channel (или папкой)
  image_file: <путь>         — карточка поста (относительно корня репозитория)
  notify: true|false         — пуш-уведомление подписчикам
Поля, дописываемые после публикации: status: published, published_at,
message_id, channel_id, url, image.

Проверки перед POST: длина <= 4000; последний блок — CTA-цитата
`> **Подписывайтесь на [<метка>](<url>)** — ...`; конфиг канала —
config/channels.json (cta_label/cta_url).
После POST: GET-контроль (вложение, ссылки, длина) и запись архива.

Отчёт: local/publish-<канал>.txt (UTF-8, читать инструментом чтения файлов —
консоль в cp1251).
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import ssl
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from post_guard import assert_channel_chat_id  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
API = "https://platform-api2.max.ru"
REPORT = []


def py_api(channel_token: str, method: str, url: str, payload: Path | None,
           form_file: Path | None, out: Path | None) -> str:
    """Запасной транспорт: stdlib urllib. Используется, когда TLS curl/schannel
    не принимает сертификат Минцифры (MAX_HTTP=python, см. README)."""
    if not url.startswith("http"):
        url = f"{API}{url}"
    if form_file:
        boundary = "----mxagent" + uuid.uuid4().hex
        body = (f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="data"; '
                f'filename="{form_file.name}"\r\n'
                f"Content-Type: image/png\r\n\r\n").encode("utf-8")
        body += form_file.read_bytes()
        body += f"\r\n--{boundary}--\r\n".encode("utf-8")
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    elif payload:
        body = payload.read_bytes()
        headers = {"Content-Type": "application/json"}
    else:
        body, headers = None, {}
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", channel_token)
    for k, v in headers.items():
        req.add_header(k, v)
    ctx = ssl.create_default_context()  # системное хранилище Windows
    ca = os.environ.get("MAX_CA_CERT")
    if ca:
        ctx.load_verify_locations(cafile=ca)
    https_handler = urllib.request.HTTPSHandler(context=ctx)
    opener = urllib.request.build_opener(https_handler)
    try:
        with opener.open(req, timeout=180) as r:
            resp = r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        resp = e.read().decode("utf-8", errors="replace")
    if out:
        Path(out).write_text(resp, encoding="utf-8")
    return resp


def api(channel_token: str, method: str, url: str, payload: Path | None = None,
        out: Path | None = None, form_file: Path | None = None) -> str:
    if os.environ.get("MAX_HTTP") == "python":
        return py_api(channel_token, method, url, payload, form_file, out)
    cmd = ["curl.exe", "-s", "-X", method, "-H", f"Authorization: {channel_token}"]
    ca = os.environ.get("MAX_CA_CERT")
    if ca:
        cmd += ["--cacert", ca]
    if payload:
        cmd += ["-H", "Content-Type: application/json", "--data-binary", f"@{payload}"]
    if form_file:
        cmd += ["-F", f"data=@{form_file}"]
    cmd.append(url if url.startswith("http") else f"{API}{url}")
    if out:
        cmd += ["-o", str(out)]
    r = subprocess.run(cmd, capture_output=True)
    return (r.stdout or b"").decode("utf-8", errors="replace")


def main() -> None:
    args = sys.argv[1:]
    channel = "ainow"
    if "--channel" in args:
        i = args.index("--channel")
        channel = args[i + 1]
        del args[i:i + 2]
    post_path = Path(args[0])
    if not post_path.is_absolute():
        post_path = REPO / post_path

    cfg = json.loads((REPO / "config" / "channels.json").read_text(encoding="utf-8"))
    ch = next((c for c in cfg["channels"] if c["slug"] == channel), None)
    if not ch:
        raise SystemExit(f"канал {channel!r} не найден в config/channels.json")
    cta_label, cta_url = ch.get("cta_label"), ch.get("cta_url")
    if not (cta_label and cta_url):
        raise SystemExit(f"для {channel!r} нет cta_label/cta_url")

    tokens = json.loads((REPO / "local" / "tokens.json").read_text(encoding="utf-8"))
    tok = tokens.get(channel, {}).get("token")
    chat_id = tokens.get(channel, {}).get("chat_id")
    if not (tok and chat_id):
        raise SystemExit(f"в local/tokens.json нет token/chat_id для {channel!r}")
    # Сторож: каналы — только отрицательный chat_id (диалоги/группы запрещены).
    assert_channel_chat_id(chat_id, tool="publish_post")

    raw = post_path.read_text(encoding="utf-8")
    m = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n?", raw, re.S)
    if not m:
        raise SystemExit("нет front matter")
    fm_text = m.group(1)
    fm = {}
    for line in fm_text.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    text = raw[m.end():].strip()

    if fm.get("channel") != channel:
        raise SystemExit(f"front matter channel={fm.get('channel')!r} != --channel {channel!r}")

    # --- проверки перед отправкой ---
    if len(text) > 4000:
        raise SystemExit(f"длина текста {len(text)} > 4000")
    cta_re = re.compile(
        rf"^> \*\*Подписывайтесь на \[{re.escape(cta_label)}\]\({re.escape(cta_url)}\)\*\* — .+$",
        re.M)
    if not cta_re.search(text):
        raise SystemExit("нет CTA-цитаты в требуемом формате")
    # '>' допустим только в CTA-строке
    stray = [ln for ln in text.splitlines() if ln.startswith(">") and not cta_re.match(ln)]
    if stray:
        raise SystemExit(f"литеральные '>' вне CTA: {stray[:2]}")

    # --- загрузка изображения ---
    image_file = fm.get("image_file")
    attachments = []
    if image_file:
        img_path = REPO / image_file
        if not img_path.exists():
            raise SystemExit(f"карточка не найдена: {img_path}")
        up_resp = api(tok, "POST", "/uploads?type=image")
        up_url = json.loads(up_resp).get("url")
        if not up_url:
            raise SystemExit(f"POST /uploads без url: {up_resp[:200]}")
        up_done = api(tok, "POST", up_url, form_file=img_path)
        up_json = json.loads(up_done)
        img_token = (up_json.get("photos", {}).get("0", {}) or {}).get("token")
        if not img_token:
            raise SystemExit(f"upload без токена: {up_done[:200]}")
        attachments = [{"type": "image", "payload": {"token": img_token}}]

    # --- POST /messages ---
    payload = {"text": text, "format": "markdown", "notify": fm.get("notify") == "true"}
    if attachments:
        payload["attachments"] = attachments
    pay_f = REPO / "local" / f"publish-payload-{channel}.json"
    pay_f.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    post_resp = api(tok, "POST", f"/messages?chat_id={chat_id}", payload=pay_f)
    try:
        resp = json.loads(post_resp)
    except json.JSONDecodeError:
        raise SystemExit(f"POST /messages не JSON: {post_resp[:200]}")
    if not resp.get("success", True) or "message" not in resp:
        raise SystemExit(f"POST /messages ошибка: {post_resp[:300]}")
    msg = resp["message"]
    mid = msg.get("body", {}).get("mid")
    url = msg.get("url") or ""
    if not mid:
        raise SystemExit(f"POST без mid: {post_resp[:300]}")

    # --- GET-контроль ---
    time.sleep(0.6)
    get_f = REPO / "local" / f"publish-verify-{channel}.json"
    api(tok, "GET", f"/messages/{mid}", out=get_f)
    body = json.loads(get_f.read_text(encoding="utf-8"))["body"]
    t2 = body["text"]
    markup = body.get("markup") or []
    checks = {
        "вложение 1": len(body.get("attachments") or []) == (1 if image_file else 0),
        "длина <=4000": len(t2) <= 4000,
        "CTA в конце": f"Подписывайтесь на {cta_label}" in t2[-200:],
        "нет '>' в тексте": ">" not in t2,
        "все ссылки на месте": all(
            u in [x.get("url") for x in markup]
            for u in re.findall(r"\]\((https?://[^)]+)\)", text)),
    }
    for k, v in checks.items():
        REPORT.append(f"{'PASS' if v else 'FAIL'}: {k}")
    if not all(checks.values()):
        REPORT.append(f"FAIL: POST вернул успех, но контроль не пройден; mid={mid}")
        raise SystemExit("контроль FAIL, см. отчёт")

    # --- архив: дописываем front matter ---
    now = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%dT%H:%M:%S+03:00")
    img_url = ""
    if image_file:
        atts = body.get("attachments") or []
        img_url = (atts[0].get("payload", {}) or {}).get("url", "") if atts else ""
    fm_out = {"channel": channel, "status": "published", "format": "markdown",
              "notify": fm.get("notify", "true"), "published_at": now,
              "message_id": mid, "channel_id": str(chat_id)}
    if url:
        fm_out["url"] = url
    if img_url:
        fm_out["image"] = img_url
    fm_lines = "\n".join(f"{k}: {v}" for k, v in fm_out.items())
    post_path.write_text(f"---\n{fm_lines}\n---\n\n{text}\n", encoding="utf-8", newline="\n")

    REPORT.append(f"OK: {post_path.name} -> {url or mid}")
    REPORT.append(f"текст {len(t2)} симв., разметка {len(markup)}")
    (REPO / "local" / f"publish-{channel}.txt").write_text("\n".join(REPORT), encoding="utf-8")
    print("ok")


if __name__ == "__main__":
    main()
