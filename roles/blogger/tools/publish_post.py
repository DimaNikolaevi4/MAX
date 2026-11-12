# -*- coding: utf-8 -*-
"""Публикация поста в канал MAX (параметризовано по каналу).

Использование:
  python roles/blogger/tools/publish_post.py [--channel ainow] <post.md>

Транспорт (раздел 5 AGENTS.md, TLS-проблемы 06.11):
  $env:MAX_HTTP='python'                          # весь HTTP на stdlib urllib
  $env:MAX_CA_CERT=local/russian_ca_bundle.pem    # доверие += бандл Минцифры
  По умолчанию HTTP идёт через curl.exe (--cacert, если MAX_CA_CERT задан);
  schannel не принимает российскую цепочку iu.oneme.ru даже с --cacert,
  поэтому для загрузки обложки на Windows использовать MAX_HTTP=python.

Файл поста: front matter + тело (Markdown). Обязательные поля front matter:
  channel: <slug>            — должен совпадать с --channel (или папкой)
  image_file: <путь>         — карточка поста (относительно корня репозитория)
  video_file: <путь>         — видео вместо карточки (что-то одно: image_file
                               или video_file); видео и есть обложка поста
  video_source: <канал>:<mid> — откуда взять видео, если файла нет на этой
                               машине (скачивание с CDN по GET /messages/{mid})
  notify: true|false         — пуш-уведомление подписчикам
Поля, дописываемые после публикации: status: published, published_at,
message_id, channel_id, url, image.

Проверки перед POST: длина <= 4000; последний блок — CTA-цитата
`> **Подписывайтесь на [<метка>](<url>)** — ...`; конфиг канала —
roles/blogger/config/channels.json (cta_label/cta_url).
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

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / ".git").exists())))
from shared.paths import REPO, CONFIG, ensure_publish_allowed  # noqa: E402
from shared.post_guard import assert_channel_chat_id  # noqa: E402
from shared.text_check import check_text, format_issue  # noqa: E402
from shared.readability import check_readability, format_issue as format_read_issue  # noqa: E402
from shared.lexicon import check_lexicon  # noqa: E402
API = "https://platform-api2.max.ru"
REPORT = []


MIME = {".mp4": "video/mp4", ".mov": "video/quicktime",
        ".mkv": "video/x-matroska", ".webm": "video/webm"}
READY_DELAYS = (5, 10, 20, 30, 60)


def py_api(channel_token: str, method: str, url: str, payload: Path | None,
           form_file: Path | None, out: Path | None,
           mime: str = "image/png") -> str:
    """Запасной транспорт: stdlib urllib. Используется, когда TLS curl/schannel
    не принимает сертификат Минцифры (MAX_HTTP=python, см. README)."""
    if not url.startswith("http"):
        url = f"{API}{url}"
    if form_file:
        boundary = "----mxagent" + uuid.uuid4().hex
        body = (f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="data"; '
                f'filename="{form_file.name}"\r\n'
                f"Content-Type: {mime}\r\n\r\n").encode("utf-8")
        body += form_file.read_bytes()
        body += f"\r\n--{boundary}--\r\n".encode("utf-8")
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    elif payload:
        body = payload.read_bytes()
        headers = {"Content-Type": "application/json"}
    elif method in ("POST", "PUT", "PATCH"):
        # API ждёт тело: без Content-Length запрос к /uploads возвращает пустой ответ
        body, headers = b"{}", {"Content-Type": "application/json"}
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
        out: Path | None = None, form_file: Path | None = None,
        mime: str = "image/png") -> str:
    if os.environ.get("MAX_HTTP") == "python":
        return py_api(channel_token, method, url, payload, form_file, out, mime)
    cmd = ["curl.exe", "-s", "-X", method, "-H", f"Authorization: {channel_token}"]
    ca = os.environ.get("MAX_CA_CERT")
    if ca:
        cmd += ["--cacert", ca]
    if payload:
        cmd += ["-H", "Content-Type: application/json", "--data-binary", f"@{payload}"]
    if form_file:
        cmd += ["-F", f"data=@{form_file};type={mime}"]
    cmd.append(url if url.startswith("http") else f"{API}{url}")
    if out:
        cmd += ["-o", str(out)]
    r = subprocess.run(cmd, capture_output=True)
    return (r.stdout or b"").decode("utf-8", errors="replace")


def plain_text(md: str) -> str:
    """LanguageTool должен читать человеческий текст, а не markdown:
    убираем ссылки (оставляя текст), выделение, цитаты и заголовки."""
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", md)
    t = re.sub(r"[*_`]{1,3}", "", t)
    t = re.sub(r"^>\s?", "", t, flags=re.M)
    t = re.sub(r"^#{1,6}\s?", "", t, flags=re.M)
    return t


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

    cfg = json.loads((CONFIG / "channels.json").read_text(encoding="utf-8"))
    ch = next((c for c in cfg["channels"] if c["slug"] == channel), None)
    if not ch:
        raise SystemExit(f"канал {channel!r} не найден в roles/blogger/config/channels.json")
    ensure_publish_allowed(channel, tool="publish_post")
    if not (ch.get("cta_label") and ch.get("cta_url")):
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
    # CTA можно переопределить во front matter поста (рекламные посты).
    cta_label = fm.get("cta_label") or ch.get("cta_label")
    cta_url = fm.get("cta_url") or ch.get("cta_url")

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

    # --- na100: атрибуция/ссылки на источники в пост не попадают ---
    # Полная (проверяемая) атрибуция живёт только в черновике выпуска
    # (channels/<slug>/digests/<дата>-draft.json, лежит в git); публикуемый
    # текст её не содержит и на последнем этапе вычищается; лимит 4000
    # считается без неё (решение владельца 12.11.2026). Гейт: в тексте
    # допустима единственная ссылка — CTA на канал.
    if channel == "na100":
        links = re.findall(r"\[[^\]]+\]\(([^)\s]+)\)", text)
        bad = sorted({u for u in links if u != cta_url})
        if bad:
            raise SystemExit(
                "в тексте есть ссылки не из CTA — по методологии na100 "
                "полная атрибуция живёт в черновике выпуска и из текста "
                "вычищается до публикации: " + ", ".join(bad[:3]))

    # --- проверка русского языка (LanguageTool) ---
    spellcheck = "--no-spellcheck" not in args
    if not spellcheck:
        args.remove("--no-spellcheck")
    if spellcheck:
        spell_ignore = [w.strip() for w in (fm.get("spell_ignore") or "").split(",") if w.strip()]
        # канальный список исключений: channels/<slug>/spell-ignore.json
        ign_path = REPO / "roles" / "blogger" / "channels" / channel / "spell-ignore.json"
        if ign_path.exists():
            ign_data = json.loads(ign_path.read_text(encoding="utf-8"))
            spell_ignore = sorted(
                {w.strip() for w in spell_ignore}
                | {w.strip() for w in ign_data.get("words", []) if w.strip()})
        spell = check_text(plain_text(text), ignore_words=spell_ignore)
        if spell.get("status") == "unavailable":
            REPORT.append("WARN: проверка орфографии недоступна: " + spell.get("message", ""))
        else:
            for issue in spell.get("errors") or []:
                REPORT.append("FAIL: " + format_issue(issue))
            for issue in spell.get("warnings") or []:
                REPORT.append("WARN: " + format_issue(issue))
            REPORT.append("проверка текста: " + spell.get("message", ""))
            if spell.get("ignored"):
                REPORT.append(f"исключённые слова: {spell['ignored']}")
            if spell.get("errors"):
                (REPO / f"local/publish-{channel}.txt").write_text(
                    "\n".join(REPORT), encoding="utf-8")
                raise SystemExit(
                    f"орфография/грамматика: ошибок {len(spell['errors'])}, см. отчёт")

    # --- эвристики читаемости (только предупреждения, не блокируют) ---
    for issue in check_readability(plain_text(text)):
        REPORT.append("WARN (читаемость): " + format_read_issue(issue))

    # --- сканер штампов humanizer-ru (опционально, только предупреждения) ---
    lex_ign_path = REPO / "roles" / "blogger" / "channels" / channel / "lexicon-ignore.json"
    lex_ignore = []
    if lex_ign_path.exists():
        lex_ignore = [c.strip() for c in
                      json.loads(lex_ign_path.read_text(encoding="utf-8")).get("categories", [])
                      if c.strip()]
    lex = check_lexicon(plain_text(text), ignore_categories=lex_ignore)
    if lex.get("status") == "unavailable":
        REPORT.append("WARN (лексика): сканер недоступен: " + lex.get("message", ""))
    else:
        for item in lex.get("items") or []:
            REPORT.append("WARN (лексика): " + item)
        REPORT.append("сканер лексики: " + lex.get("message", ""))

    # --- калибровочный лог слоя 3 (дополнение к отчёту, не влияет на выпуск) ---
    # Сырые баллы по каждому выпуску копятся в канальном jsonl; по ним
    # калибруется порог номинальности (сейчас 2.5 откалиброван под marketing).
    try:
        if lex.get("status") == "ok":
            rec = {
                "type": "scan",
                "ts": datetime.now(timezone(timedelta(hours=3))).isoformat(),
                "post": post_path.name,
                "readability_warn": len(check_readability(plain_text(text))),
                **(lex.get("metrics") or {}),
            }
            cal = REPO / "roles" / "blogger" / "channels" / channel / \
                "lexicon-calibration.jsonl"
            with cal.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:  # noqa: BLE001
        REPORT.append(f"WARN (лексика): калибровочный лог не записан: {e!r}"[:160])

    # --- загрузка медиа: картинка или видео (видео заменяет обложку) ---
    image_file = fm.get("image_file")
    video_file = fm.get("video_file")
    if image_file and video_file:
        raise SystemExit("укажите что-то одно: image_file или video_file")
    attachments = []
    media_kind = ""
    if video_file and not (REPO / video_file).exists() and fm.get("video_source"):
        # файла нет на этой машине: берём ссылку на файл из поста-источника
        src_channel, _, src_mid = fm["video_source"].partition(":")
        src_token = tokens.get(src_channel, {}).get("token")
        if not src_token or not src_mid:
            raise SystemExit(f"video_source не разобран: {fm['video_source']!r}")
        src_file = REPO / "local" / "media-cache" / f"{src_mid.replace('.', '_')}.mp4"
        src_file.parent.mkdir(parents=True, exist_ok=True)
        src_resp = api(src_token, "GET", f"/messages/{src_mid}",
                       out=src_file.with_suffix(".json"))
        try:
            src_url = (((json.loads(src_resp)["body"].get("attachments") or [{}])[0]
                        .get("payload") or {}).get("url"))
        except (KeyError, IndexError, json.JSONDecodeError):
            src_url = None
        if not src_url:
            raise SystemExit(f"в {fm['video_source']} нет видео: {src_resp[:200]}")
        req = urllib.request.Request(src_url, headers={"User-Agent": "curl/8.13.0"})
        ctx_dl = ssl.create_default_context()
        ca_dl = os.environ.get("MAX_CA_CERT")
        if ca_dl:
            ctx_dl.load_verify_locations(cafile=ca_dl)
        with urllib.request.urlopen(req, timeout=600, context=ctx_dl) as r, \
                src_file.open("wb") as fh:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
        video_file = str(src_file.relative_to(REPO)).replace("\\", "/")
        REPORT.append(f"видео скачано из {fm['video_source']}: {src_file.stat().st_size} Б")
    if image_file or video_file:
        media_kind = "video" if video_file else "image"
        media_path = REPO / (video_file or image_file)
        if not media_path.exists():
            raise SystemExit(f"медиа не найдено: {media_path}")
        mime = MIME.get(media_path.suffix.lower(), "application/octet-stream")
        up_resp = api(tok, "POST", f"/uploads?type={media_kind}")
        up_json_head = json.loads(up_resp)
        up_url = up_json_head.get("url")
        if not up_url:
            raise SystemExit(f"POST /uploads без url: {up_resp[:200]}")
        up_done = api(tok, "POST", up_url, form_file=media_path, mime=mime)
        try:
            up_json = json.loads(up_done)
        except json.JSONDecodeError:
            # загрузка видео на okcdn отвечает не JSON, а <retval>1</retval>;
            # токен вложения приходит в первом ответе POST /uploads
            up_json = {}
        media_token = up_json_head.get("token")
        if not media_token:
            media_token = (up_json.get("photos", {}).get("0", {}) or {}).get("token")
        if not media_token:
            media_token = (up_json.get("videos", {}).get("0", {}) or {}).get("token")
        if not media_token:
            raise SystemExit(f"upload без токена: {up_done[:200]}")
        attachments = [{"type": media_kind, "payload": {"token": media_token}}]
        if media_kind == "video":
            REPORT.append(f"видео загружено: {media_path.name} ({media_path.stat().st_size} Б)")

    # --- POST /messages ---
    payload = {"text": text, "format": "markdown", "notify": fm.get("notify") == "true"}
    if attachments:
        payload["attachments"] = attachments
    pay_f = REPO / "local" / f"publish-payload-{channel}.json"
    pay_f.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    post_resp = api(tok, "POST", f"/messages?chat_id={chat_id}", payload=pay_f)
    for delay in READY_DELAYS:
        if "attachment.not.ready" not in (post_resp or ""):
            break
        REPORT.append(f"медиа ещё обрабатывается, повтор через {delay} с")
        time.sleep(delay)
        post_resp = api(tok, "POST", f"/messages?chat_id={chat_id}", payload=pay_f)
    try:
        resp = json.loads(post_resp)
    except json.JSONDecodeError:
        raise SystemExit(f"POST /messages не JSON: {post_resp[:200]}")
    if not resp.get("success", True) or not isinstance(resp.get("message"), dict):
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
        "вложение 1": len(body.get("attachments") or []) == (1 if media_kind else 0),
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
    media_url = ""
    media_extra = {}
    if media_kind:
        atts = body.get("attachments") or []
        media_url = (atts[0].get("payload", {}) or {}).get("url", "") if atts else ""
        if media_kind == "video" and atts:
            if atts[0].get("duration"):
                media_extra["video_duration"] = atts[0]["duration"]
            media_extra["media_count"] = 1
    fm_out = {"channel": channel, "status": "published", "format": "markdown",
              "notify": fm.get("notify", "true"), "published_at": now,
              "message_id": mid, "channel_id": str(chat_id)}
    if url:
        fm_out["url"] = url
    if video_file:
        fm_out["video_file"] = video_file
    if image_file:
        fm_out["image_file"] = image_file
    if media_url:
        fm_out["video" if media_kind == "video" else "image"] = media_url
    fm_out.update(media_extra)
    fm_lines = "\n".join(f"{k}: {v}" for k, v in fm_out.items())
    post_path.write_text(f"---\n{fm_lines}\n---\n\n{text}\n", encoding="utf-8", newline="\n")

    REPORT.append(f"OK: {post_path.name} -> {url or mid}")
    REPORT.append(f"текст {len(t2)} симв., разметка {len(markup)}")
    (REPO / "local" / f"publish-{channel}.txt").write_text("\n".join(REPORT), encoding="utf-8")
    print("ok")


if __name__ == "__main__":
    main()
