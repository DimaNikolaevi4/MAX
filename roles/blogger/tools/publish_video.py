# -*- coding: utf-8 -*-
"""Публикация поста с медиа в канал MAX (формат «Забавное»).

Использование:
  python roles/blogger/tools/publish_video.py [--channel zabava] [--video <файл>] [--dry-run] <post.md>

Файл поста: front matter + короткий текст.
  channel: <slug>            — должен совпадать с --channel (или папкой)
  video_file: <путь>         — одно видео; абсолютный путь или от корня репозитория
  image_files: <п1>|<п2>     — фото или альбом до 6 штук, пути через «|»
  max_text: <число>          — необязательное исключение из лимита 200 символов
  spell_ignore: <слова>      — необязательный список слов через запятую
  notify: true|false         — пуш-уведомление (в каналах всегда true)
  status: draft              — опубликованный пост повторно не отправляется

Что делает:
  * проверяет медиа (формат, размер, число файлов), длину и стиль текста;
  * проверяет орфографию, пунктуацию и грамматику (LanguageTool);
  * выбирает призыв из roles/blogger/channels/<slug>/cta-phrases.json так,
    чтобы он не повторялся в последних 6 постах;
  * оформляет слово из cta_label жирной ссылкой на cta_url;
  * загружает видео или фото (POST /uploads?type=video|image -> multipart),
    отправляет пост, повторяет при attachment.not.ready;
  * GET-контроль: медиа на месте, текст совпадает, ссылка и жирный на месте;
  * дописывает front matter и обновляет cta-phrases.json (recent, by_post).

Структура поста: видео/фото -> короткий текст -> пустая строка -> призыв.

Транспорт: stdlib urllib. Доверие к сертификату Минцифры:
  $env:MAX_CA_CERT=local/russian_ca_bundle.pem
Если переменная не задана, берётся local/russian_ca_bundle.pem при наличии.

Отчёт: local/publish-<канал>-video.txt (UTF-8, консоль в cp1251).
"""
import json
import os
import random
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / ".git").exists())))
from shared.paths import REPO, CONFIG  # noqa: E402
from shared.post_guard import assert_channel_chat_id  # noqa: E402
from shared.text_check import check_text, format_issue  # noqa: E402

API = "https://platform-api2.max.ru"
MSK = timezone(timedelta(hours=3))
REPORT = []
VIDEO_EXT = {".mp4": "video/mp4", ".mov": "video/quicktime",
             ".mkv": "video/x-matroska", ".webm": "video/webm"}
IMAGE_EXT = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
             ".webp": "image/webp", ".gif": "image/gif"}
MAX_VIDEO_BYTES = 250 * 1024**2
MAX_IMAGE_BYTES = 50 * 1024**2
MAX_IMAGES = 6
MAX_TEXT = 200
READY_DELAYS = [2, 5, 10, 20, 30, 45]
RECENT_KEEP = 6


def now() -> str:
    return datetime.now(MSK).isoformat(timespec="seconds")


def ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ca = os.environ.get("MAX_CA_CERT") or str(REPO / "local" / "russian_ca_bundle.pem")
    if ca and Path(ca).exists():
        ctx.load_verify_locations(cafile=ca)
    return ctx


def http(url: str, method: str = "GET", token: str | None = None,
         data: bytes | None = None, headers: dict | None = None,
         timeout: int = 600) -> tuple[str, int]:
    """Возвращает (тело, HTTP-код). Тело читается и при ошибках."""
    if not url.startswith("http"):
        url = API + url
    req = urllib.request.Request(url, data=data, method=method)
    if token:
        req.add_header("Authorization", token)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl_context()))
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace"), r.status
    except urllib.error.HTTPError as e:
        return e.read().decode("utf-8", errors="replace"), e.code
    except Exception as e:  # noqa: BLE001
        return f"transport error: {e!r}", 0


def find_token(obj):
    if isinstance(obj, dict):
        if isinstance(obj.get("token"), str):
            return obj["token"]
        for v in obj.values():
            t = find_token(v)
            if t:
                return t
    elif isinstance(obj, list):
        for v in obj:
            t = find_token(v)
            if t:
                return t
    return None


def upload_media(token: str, path: Path, kind: str) -> str:
    """POST /uploads?type=video|image, затем multipart. Возвращает токен."""
    ext_map = VIDEO_EXT if kind == "video" else IMAGE_EXT
    last = ""
    for attempt in range(3):
        body, code = http(f"/uploads?type={kind}", "POST", token=token)
        try:
            data = json.loads(body)
            up_url = data["url"]
        except Exception:  # noqa: BLE001
            last = f"/uploads HTTP {code}: {body[:200]}"
            time.sleep(2 * (attempt + 1))
            continue

        attachment_token = data.get("token")
        boundary = "----mxmedia" + uuid.uuid4().hex
        mime = ext_map[path.suffix.lower()]
        head = (f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="data"; '
                f'filename="{path.name}"\r\n'
                f"Content-Type: {mime}\r\n\r\n").encode("utf-8")
        payload = head + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode("utf-8")
        up_body, up_code = http(
            up_url, "POST",
            data=payload,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            timeout=1800)
        if not attachment_token and up_body.strip().startswith("{"):
            try:
                attachment_token = find_token(json.loads(up_body))
            except Exception:  # noqa: BLE001
                attachment_token = None
        if attachment_token and 200 <= up_code < 300:
            return attachment_token
        last = f"upload HTTP {up_code}: {up_body[:200]}"
        time.sleep(2 * (attempt + 1))
    raise SystemExit(last or f"не удалось загрузить {kind}")


def post_message(token: str, chat_id: int, text: str, attachments: list,
                 notify: bool) -> tuple[str, str, str]:
    payload = {
        "text": text,
        "format": "markdown",
        "notify": notify,
        "attachments": attachments,
    }
    body, code = http(f"/messages?chat_id={chat_id}", "POST", token=token,
                      data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                      headers={"Content-Type": "application/json"})
    try:
        obj = json.loads(body)
    except json.JSONDecodeError:
        return "", "", f"HTTP {code}: {body[:200]}"
    if obj.get("code"):
        return "", "", f"{obj.get('code')}: {obj.get('message')}"
    msg = obj.get("message") or {}
    mid = (msg.get("body") or {}).get("mid")
    if not mid:
        return "", "", f"нет mid, HTTP {code}: {body[:200]}"
    return mid, msg.get("url") or "", ""


def send_with_retry(token, chat_id, text, attachments, notify):
    mid, url, err = post_message(token, chat_id, text, attachments, notify)
    for delay in READY_DELAYS:
        if mid or "attachment.not.ready" not in err:
            break
        REPORT.append(f"медиа ещё обрабатывается, повтор через {delay} с")
        time.sleep(delay)
        mid, url, err = post_message(token, chat_id, text, attachments, notify)
    return mid, url, err


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_report(channel: str) -> None:
    (REPO / "local" / f"publish-{channel}-video.txt").write_text(
        "\n".join(REPORT), encoding="utf-8")


def parse_post(path: Path) -> tuple[dict, str]:
    raw = path.read_text(encoding="utf-8")
    m = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n?", raw, re.S)
    if not m:
        raise SystemExit("нет front matter")
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    return fm, raw[m.end():].strip()


def resolve_path(value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else REPO / p


def pick_cta(channel: str, cfg: dict) -> tuple[str, Path, dict]:
    path = REPO / "roles" / "blogger" / "channels" / channel / "cta-phrases.json"
    if not path.exists():
        raise SystemExit(f"нет пула призывов: {path}")
    data = load_json(path)
    pool = [p for p in (data.get("pool") or []) if p.strip()]
    if not pool:
        raise SystemExit(f"пул призывов пуст: {path}")
    recent = list(data.get("recent") or [])
    blocked = set(recent[-RECENT_KEEP:])
    available = [p for p in pool if p not in blocked] or pool
    phrase = random.SystemRandom().choice(available)
    label = cfg.get("cta_label") or ""
    if label and label not in phrase:
        raise SystemExit(f"в призыве нет слова {label!r}: {phrase!r}")
    return phrase, path, data


def build_cta(phrase: str, cfg: dict) -> str:
    label, url = cfg["cta_label"], cfg["cta_url"]
    return phrase.replace(label, f"**[{label}]({url})**", 1)


def validate_body(body: str, max_text: int = MAX_TEXT) -> None:
    if not body:
        raise SystemExit("пустой текст поста")
    if len(body) > max_text:
        raise SystemExit(f"текст {len(body)} символов > {max_text}")
    lines = body.splitlines()
    if max_text <= MAX_TEXT and len(lines) > 2:
        raise SystemExit(f"текст должен быть 1–2 строки, сейчас {len(lines)}")
    if body.rstrip().endswith("."):
        raise SystemExit("текст не должен заканчиваться точкой")
    if "http" in body.lower() or "max.ru/" in body.lower():
        raise SystemExit("ссылки в тексте запрещены — ссылка только в призыве")
    if "#" in body:
        raise SystemExit("хештеги запрещены")
    if "каждый день" in body.lower():
        raise SystemExit("обещание «каждый день» запрещено")
    if "**" in body or "](" in body:
        raise SystemExit("разметка в тексте не нужна — призыв добавляется автоматически")


def verify(token: str, mid: str, body: str, phrase: str, cfg: dict,
           expected_types: list[str]) -> tuple[dict, dict]:
    get_body, code = http(f"/messages/{mid}", "GET", token=token)
    try:
        msg = json.loads(get_body)
    except json.JSONDecodeError:
        raise SystemExit(f"GET /messages/{mid} не JSON, HTTP {code}: {get_body[:200]}")
    b = msg.get("body") or {}
    text = b.get("text") or ""
    atts = b.get("attachments") or []
    markup = b.get("markup") or []
    expected = f"{body}\n\n{phrase}"
    label = cfg["cta_label"]
    label_at = text.rfind(label)
    strong_ok = any(
        m.get("type") == "strong"
        and m.get("from", 0) <= label_at < m.get("from", 0) + m.get("length", 0)
        for m in markup)
    link_ok = any(
        m.get("type") == "link"
        and m.get("url") == cfg["cta_url"]
        and m.get("from", 0) <= label_at < m.get("from", 0) + m.get("length", 0)
        for m in markup)
    checks = {
        "вложений: %d" % len(expected_types): len(atts) == len(expected_types),
        "типы вложений": [a.get("type") for a in atts] == expected_types,
        "текст совпадает": text == expected,
        "призыв в конце": text.rstrip().endswith(phrase),
        "ссылка на канал на слове": link_ok,
        "слово жирное": strong_ok,
        "нет markdown-остатков": "**" not in text and "](" not in text,
    }
    for k, v in checks.items():
        REPORT.append(f"{'PASS' if v else 'FAIL'}: {k}")
    return checks, {"text": text, "attachments": atts, "markup": markup, "msg": msg}


def main() -> None:
    args = sys.argv[1:]
    channel = "zabava"
    if "--channel" in args:
        i = args.index("--channel")
        channel = args[i + 1]
        del args[i:i + 2]
    video_override = None
    if "--video" in args:
        i = args.index("--video")
        video_override = args[i + 1]
        del args[i:i + 2]
    dry_run = "--dry-run" in args
    if dry_run:
        args.remove("--dry-run")
    spellcheck = "--no-spellcheck" not in args
    if not spellcheck:
        args.remove("--no-spellcheck")
    if len(args) != 1:
        raise SystemExit("Использование: publish_video.py [--channel zabava] [--video файл] "
                         "[--dry-run] [--no-spellcheck] <post.md>")

    post_path = Path(args[0])
    if not post_path.is_absolute():
        post_path = REPO / post_path

    cfg_all = load_json(CONFIG / "channels.json")
    cfg = next((c for c in cfg_all["channels"] if c["slug"] == channel), None)
    if not cfg:
        raise SystemExit(f"канал {channel!r} не найден в channels.json")
    for key in ("cta_label", "cta_url"):
        if not cfg.get(key):
            raise SystemExit(f"для {channel!r} нет {key}")

    tokens = load_json(REPO / "local" / "tokens.json")
    entry = tokens.get(channel) or {}
    token, chat_id = entry.get("token"), entry.get("chat_id")
    if not (token and chat_id):
        raise SystemExit(f"в local/tokens.json нет token/chat_id для {channel!r}")
    assert_channel_chat_id(chat_id, tool="publish_video")

    fm, body = parse_post(post_path)
    if fm.get("channel") != channel:
        raise SystemExit(f"front matter channel={fm.get('channel')!r} != --channel {channel!r}")
    status = fm.get("status", "draft")
    if status == "published" and not dry_run:
        raise SystemExit("пост уже опубликован (status: published)")

    try:
        max_text = int(fm.get("max_text") or MAX_TEXT)
    except ValueError:
        raise SystemExit(f"max_text должен быть числом: {fm.get('max_text')!r}")
    spell_ignore = [w.strip() for w in (fm.get("spell_ignore") or "").split(",") if w.strip()]
    validate_body(body, max_text)

    video_value = video_override or fm.get("video_file")
    images_value = fm.get("image_files")
    if video_value and images_value:
        raise SystemExit("укажите что-то одно: video_file или image_files")
    media = []  # [(kind, Path)]
    if video_value:
        video_path = resolve_path(video_value)
        if not video_path.exists():
            raise SystemExit(f"видео не найдено: {video_path}")
        ext = video_path.suffix.lower()
        if ext not in VIDEO_EXT:
            raise SystemExit(f"формат {ext} не поддерживается: {sorted(VIDEO_EXT)}")
        if video_path.stat().st_size > MAX_VIDEO_BYTES:
            raise SystemExit(f"видео {video_path.stat().st_size / 1024**2:.1f} МБ > 250 МБ")
        media = [("video", video_path)]
    elif images_value:
        raw_paths = [p.strip() for p in images_value.split("|") if p.strip()]
        if not 1 <= len(raw_paths) <= MAX_IMAGES:
            raise SystemExit(f"фото должно быть от 1 до {MAX_IMAGES}, сейчас {len(raw_paths)}")
        for raw in raw_paths:
            img_path = resolve_path(raw)
            if not img_path.exists():
                raise SystemExit(f"фото не найдено: {img_path}")
            ext = img_path.suffix.lower()
            if ext not in IMAGE_EXT:
                raise SystemExit(f"формат фото {ext} не поддерживается: {sorted(IMAGE_EXT)}")
            if img_path.stat().st_size > MAX_IMAGE_BYTES:
                raise SystemExit(f"фото {img_path.name} больше 50 МБ")
            media.append(("image", img_path))
    else:
        raise SystemExit("не указан video_file или image_files (front matter) / --video")
    expected_types = [kind for kind, _ in media]

    phrase, cta_path, cta_data = pick_cta(channel, cfg)
    cta_md = build_cta(phrase, cfg)
    text = f"{body}\n\n{cta_md}"
    if len(text) > 4000:
        raise SystemExit(f"итоговый текст {len(text)} > 4000")

    REPORT.append(f"канал: {channel} ({cfg.get('title', '')}), chat_id={chat_id}")
    REPORT.append(f"пост: {post_path.name}, статус: {status}")
    for kind, path in media:
        REPORT.append(f"{kind}: {path} ({path.stat().st_size / 1024**2:.2f} МБ)")
    REPORT.append(f"текст: {len(body)} символов, строк {len(body.splitlines())}, "
                  f"лимит {max_text}, без точки в конце")
    REPORT.append(f"призыв: {phrase}")
    REPORT.append("итоговый текст (markdown):")
    REPORT.append(text)

    spell = None
    if spellcheck:
        spell = check_text(f"{body}\n\n{phrase}", ignore_words=spell_ignore)
        if spell["status"] == "unavailable":
            REPORT.append("WARN: проверка орфографии недоступна: " + spell["message"])
        else:
            for issue in spell["errors"]:
                REPORT.append("ОШИБКА: " + format_issue(issue))
            for issue in spell["warnings"]:
                REPORT.append("ЗАМЕЧАНИЕ: " + format_issue(issue))
            REPORT.append("проверка текста: " + spell["message"])
            if spell.get("ignored"):
                REPORT.append(f"исключено слов: {spell['ignored']}")
    else:
        REPORT.append("SKIP: проверка орфографии отключена (--no-spellcheck)")

    if spell and spell["errors"]:
        write_report(channel)
        raise SystemExit(f"орфография/пунктуация: ошибок {len(spell['errors'])}, см. отчёт")

    if dry_run:
        REPORT.append("DRY-RUN: загрузка и отправка не выполнялись")
        write_report(channel)
        print("dry-run ok")
        return

    REPORT.append(f"загрузка медиа: файлов {len(media)}...")
    attachments = []
    for kind, path in media:
        media_token = upload_media(token, path, kind)
        attachments.append({"type": kind, "payload": {"token": media_token}})
        REPORT.append(f"  {kind} {path.name}: токен {media_token[:12]}...")

    mid, url, err = send_with_retry(token, chat_id, text, attachments,
                                    fm.get("notify", "true") != "false")
    if not mid:
        REPORT.append(f"FAIL: отправка не удалась: {err}")
        write_report(channel)
        raise SystemExit("POST /messages не удался, см. отчёт")

    checks, got = verify(token, mid, body, phrase, cfg, expected_types)
    if not all(checks.values()):
        REPORT.append(f"FAIL: контроль не пройден, mid={mid}")
        write_report(channel)
        raise SystemExit("контроль FAIL, см. отчёт")

    duration = None
    media_urls = []
    for att in got["attachments"]:
        payload = att.get("payload") or {}
        if att.get("type") == "video":
            duration = att.get("duration")
            if duration is None:
                duration = payload.get("duration")
        if payload.get("url"):
            media_urls.append(payload["url"])

    fm_out = {
        "channel": channel,
        "status": "published",
        "format": "markdown",
        "notify": fm.get("notify", "true"),
        "published_at": now(),
        "message_id": mid,
        "channel_id": str(chat_id),
    }
    if url:
        fm_out["url"] = url
    if video_value:
        fm_out["video_file"] = video_value
        if duration is not None:
            fm_out["video_duration"] = str(duration)
        if media_urls:
            fm_out["video"] = media_urls[0]
    else:
        fm_out["image_files"] = " | ".join(raw for raw in
                                           (p.strip() for p in images_value.split("|"))
                                           if raw)
    if media_urls and not video_value:
        fm_out["images"] = " | ".join(media_urls)
    fm_out["media_count"] = str(len(got["attachments"]))
    fm_out["cta"] = phrase
    fm_lines = "\n".join(f"{k}: {v}" for k, v in fm_out.items())
    post_path.write_text(f"---\n{fm_lines}\n---\n\n{body}\n", encoding="utf-8", newline="\n")

    recent = list(cta_data.get("recent") or []) + [phrase]
    cta_data["recent"] = recent[-RECENT_KEEP:]
    cta_data.setdefault("by_post", {})[post_path.name] = phrase
    cta_path.write_text(json.dumps(cta_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    REPORT.append(f"OK: {post_path.name} -> {url or mid}")
    REPORT.append(f"текст {len(got['text'])} симв., разметка {len(got['markup'])}, "
                  f"вложений {len(got['attachments'])}"
                  + (f", длительность {duration}" if duration is not None else ""))
    write_report(channel)
    print("ok")


if __name__ == "__main__":
    main()
