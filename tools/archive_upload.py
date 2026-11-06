# -*- coding: utf-8 -*-
"""Исполнение плана наполнения канала-архива MAX.

Использование:
  python tools/archive_upload.py [--plan local/archive-plan.json] [--limit N]
                                 [--from I] [--year YYYY] [--dry-run] [--sha]
                                 [--stop-on-error]

Что делает:
  * читает план из tools/archive_plan.py (local/archive-plan.json);
  * фото (`as: image`) конвертирует в WEBP 1920×1440 q90 и постит как `image` —
    видно в ленте на телефоне и на компьютере;
  * видео до 250 МБ (`as: video`) постит как `video` — кадр-превью и play;
  * всё остальное (`as: file`) постит как `file` — байт-в-байт;
  * файлы больше 4 ГБ режет на части по 1,9 ГБ в local/split/ и грузит
    частями, затем постит инструкцию склейки (copy /b) и sha256;
  * `--year YYYY` — залить только один год (без годовых каталогов и закрепа:
    они уходят последним общим прогоном);
  * каждый успешный пост пишет в журнал local/archive-journal.jsonl —
    повторный запуск продолжает с места остановки (докачка);
  * после каждого поста GET-контроль: тип вложения и (для файлов) имя и размер;
  * соблюдает лимит 2 сообщения/сек, повторяет отправку при
    `attachment.not.ready` с растущим интервалом;
  * ошибки не роняют прогон: пост помечается failed и остаётся в очереди.

Отчёт: local/archive-run.txt (UTF-8). Консоль — только ASCII.
"""
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
API = "https://platform-api2.max.ru"
MSK = timezone(timedelta(hours=3))
PLAN = REPO / "local" / "archive-plan.json"
JOURNAL = REPO / "local" / "archive-journal.jsonl"
REPORT = REPO / "local" / "archive-run.txt"
SPLIT_DIR = REPO / "local" / "split"
SPLIT_MANIFEST = REPO / "local" / "split-manifest.json"
WEBP_DIR = REPO / "local" / "webp"
PART = 1900 * 1024**2      # часть файла >4 ГБ (лимит MAX — 4 ГБ)
IMAGE_MAX = 1920           # MAX всё равно режет до 1920 по длинной стороне
IMAGE_QUALITY = 90
PAUSE = 0.65               # лимит 2 сообщения/сек на канал
READY_DELAYS = [2, 4, 8, 16, 32, 64, 120]


def now() -> str:
    return datetime.now(MSK).isoformat(timespec="seconds")


def load_tokens():
    data = json.loads((REPO / "local" / "tokens.json").read_text(encoding="utf-8"))
    return data["archive"]["token"], data["archive"]["chat_id"]


TOKEN, CHAT = load_tokens()


def curl(args, timeout=7200):
    r = subprocess.run(["curl.exe", "-s", "-w", "\n%{http_code}"] + args,
                       capture_output=True, timeout=timeout)
    out = (r.stdout or b"").decode("utf-8", errors="replace")
    code = ""
    if "\n" in out:
        out, code = out.rsplit("\n", 1)
    return out, code.strip()


def api(method: str, path: str, payload: dict | None = None):
    args = ["-X", method, "-H", f"Authorization: {TOKEN}"]
    if payload is not None:
        tmp = REPO / "local" / "archive-payload.json"
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        args += ["-H", "Content-Type: application/json", "--data-binary", f"@{tmp}"]
    args.append(path if path.startswith("http") else API + path)
    return curl(args)


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


def upload_media(path: Path, kind: str) -> str:
    """Загружает файл и возвращает токен вложения указанного типа."""
    last = ""
    for attempt in range(3):
        body, code = api("POST", f"/uploads?type={kind}")
        try:
            data = json.loads(body)
            up_url = data["url"]
        except Exception:  # noqa: BLE001
            last = f"/uploads {code}: {body[:160]}"
            time.sleep(2 * (attempt + 1))
            continue
        # у video/audio токен приходит сразу в ответе /uploads
        tok = data.get("token") if kind in ("video", "audio") else None
        body2, code2 = curl(["-X", "POST", "-H", "Content-Type: multipart/form-data",
                             "-F", f"data=@{path}", up_url])
        if not tok and body2.strip().startswith("{"):
            try:
                tok = find_token(json.loads(body2))
            except Exception:  # noqa: BLE001
                tok = None
        if tok:
            return tok
        last = f"upload {code2}: {body2[:160]}"
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(last or "upload failed")


def prepare_image(path: Path) -> Path:
    """Фото -> WEBP 1920×1440 q90. Кэш в local/webp (по пути и mtime)."""
    from PIL import Image, ImageOps

    try:  # HEIC/HEIF с телефонов: без этого Pillow их не открывает
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass

    st = path.stat()
    key = hashlib.sha1(f"{path}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()[:20]
    dst = WEBP_DIR / f"{key}.webp"
    if dst.exists() and dst.stat().st_mtime >= st.st_mtime:
        return dst
    WEBP_DIR.mkdir(parents=True, exist_ok=True)
    with Image.open(path) as im:
        # уже готовый webp не больше 1920 (например, скачанный из MAX) отдаём
        # как есть: лишнее поколение сжатия только портит картинку
        if (im.format == "WEBP" and max(im.size) <= IMAGE_MAX
                and im.mode in ("RGB", "RGBA")
                and getattr(im, "n_frames", 1) == 1):
            return path
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGB")
        im.thumbnail((IMAGE_MAX, IMAGE_MAX), Image.LANCZOS)
        im.save(dst, "WEBP", quality=IMAGE_QUALITY, method=6)
    return dst


def post_message(text: str, attachment_token: str | None = None, kind: str = "file"):
    payload = {"text": text, "format": "markdown", "notify": True}
    if attachment_token:
        payload["attachments"] = [{"type": kind, "payload": {"token": attachment_token}}]
    body, code = api("POST", f"/messages?chat_id={CHAT}", payload)
    try:
        msg = json.loads(body)
    except Exception:  # noqa: BLE001
        return None, f"{code}: {body[:160]}"
    if msg.get("code"):
        return None, f"{msg.get('code')}: {msg.get('message')}"
    mid = (msg.get("message") or {}).get("body", {}).get("mid")
    if not mid:
        return None, f"нет mid: {body[:160]}"
    return mid, ""


def wait_ready(text: str, token: str, kind: str = "file"):
    """Отправка с повтором при attachment.not.ready."""
    mid, err = post_message(text, token, kind)
    for delay in READY_DELAYS:
        if mid or "attachment.not.ready" not in err:
            return mid, err
        time.sleep(delay)
        mid, err = post_message(text, token, kind)
    return mid, err


def verify(mid: str, kind: str, path: Path | None):
    """GET-контроль: тип вложения, для файла — имя и размер."""
    body, _code = api("GET", f"/messages/{mid}")
    try:
        msg = json.loads(body)
    except Exception:  # noqa: BLE001
        return False, "GET не JSON"
    atts = (msg.get("body") or {}).get("attachments") or []
    if not atts:
        return False, "нет вложения"
    a = atts[0]
    if a.get("type") != kind:
        return False, f"тип {a.get('type')} вместо {kind}"
    if kind == "file":
        size = a.get("size")
        name = a.get("filename")
        ok = size == path.stat().st_size and name == path.name
        return ok, f"size={size} name={name!r}"
    if kind == "video":
        return a.get("duration") is not None, f"duration={a.get('duration')}"
    if kind == "image":
        return bool((a.get("payload") or {}).get("photo_id")), "photo_id есть"
    return True, ""


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(4 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_manifest() -> dict:
    if SPLIT_MANIFEST.exists():
        try:
            return json.loads(SPLIT_MANIFEST.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    return {}


def split_file(path: Path):
    """Режет файл на части <= PART. Кэш в local/split. Возвращает (части, sha256)."""
    st = path.stat()
    key = f"{path}|{st.st_size}|{int(st.st_mtime)}"
    man = load_manifest()
    rec = man.get(key)
    if rec:
        parts = [SPLIT_DIR / n for n in rec["parts"]]
        if all(p.exists() and p.stat().st_size == s
               for p, s in zip(parts, rec["sizes"])):
            return parts, rec["sha256"]

    SPLIT_DIR.mkdir(parents=True, exist_ok=True)
    n_parts = -(-st.st_size // PART)
    parts, sizes = [], []
    h = hashlib.sha256()
    with open(path, "rb") as src:
        for n in range(1, n_parts + 1):
            dst = SPLIT_DIR / f"{path.name}.part{n:02d}"
            left = min(PART, st.st_size - (n - 1) * PART)
            with open(dst, "wb") as out:
                while left > 0:
                    block = src.read(min(8 << 20, left))
                    if not block:
                        break
                    out.write(block)
                    h.update(block)
                    left -= len(block)
            parts.append(dst)
            sizes.append(dst.stat().st_size)
    digest = h.hexdigest()
    man[key] = {"parts": [p.name for p in parts], "sizes": sizes, "sha256": digest}
    SPLIT_MANIFEST.write_text(json.dumps(man, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    return parts, digest


def join_note(path: Path, parts, digest: str) -> str:
    """Инструкция склейки частей — отдельный пост после частей."""
    n = len(parts)
    return "\n".join([
        f"**Склейка файла:** {path.name}",
        "",
        f"Файл больше лимита MAX (4 ГБ) и выложен {n} частями по 1,9 ГБ.",
        "Скачайте все части в одну папку и склейте:",
        "",
        "Windows (cmd):",
        f'copy /b "{path.name}.part*" "{path.name}"',
        "",
        "Linux / macOS:",
        f'cat "{path.name}".part* > "{path.name}"',
        "",
        f"sha256 исходного файла: `{digest}`",
        f"Размер: {path.stat().st_size} байт",
    ])


def upload_split(e: dict):
    """Части файла >4 ГБ + пост с инструкцией склейки. Возвращает (байты, детали)."""
    path = Path(e["path"])
    if not path.exists():
        raise RuntimeError(f"нет файла {path}")
    parts, digest = split_file(path)
    sent = 0
    mids = []
    for k, part in enumerate(parts, 1):
        tok = upload_media(part, "file")
        mid, err = wait_ready(f"{e['caption']} · часть {k} из {len(parts)}", tok, "file")
        if not mid:
            raise RuntimeError(f"POST часть {k}: {err}")
        time.sleep(0.4)
        ok, why = verify(mid, "file", part)
        if not ok:
            raise RuntimeError(f"часть {k} не сошлась: {why}")
        mids.append({"mid": mid, "name": part.name, "size": part.stat().st_size})
        sent += part.stat().st_size
    mid, err = post_message(join_note(path, parts, digest))
    if not mid:
        raise RuntimeError(f"POST инструкция: {err}")
    return sent, {"parts": mids, "sha256": digest, "note_mid": mid}


def journal_add(entry: dict):
    with JOURNAL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def journal_done() -> dict:
    done = {}
    if not JOURNAL.exists():
        return done
    for line in JOURNAL.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if e.get("status") in ("done", "skipped"):
            done[e["i"]] = e
    return done


def send_media(i: int, e: dict, as_: str):
    """Один пост: image (webp), video или file. Возвращает (байты, запись)."""
    path = Path(e["path"])
    if not path.exists():
        raise RuntimeError(f"нет файла {path}")

    if as_ == "image":
        try:
            src = prepare_image(path)
        except Exception as exc:  # noqa: BLE001
            # битый/нечитаемый файл с расширением фото: кладём оригинал как file
            tok = upload_media(path, "file")
            mid, err = wait_ready(e["caption"], tok, "file")
            if not mid:
                raise RuntimeError(f"POST file вместо image ({exc}): {err}") from exc
            time.sleep(0.4)
            ok, why = verify(mid, "file", path)
            return path.stat().st_size, {"mid": mid,
                                         "status": "done" if ok else "failed",
                                         "as": "file", "fallback_from": "image",
                                         "fallback_reason": str(exc)[:120],
                                         "uploaded": path.stat().st_size,
                                         "verify": why}
        tok = upload_media(src, "image")
        mid, err = wait_ready(e["caption"], tok, "image")
        if not mid:
            raise RuntimeError(f"POST image: {err}")
        time.sleep(0.4)
        ok, why = verify(mid, "image", None)
        return src.stat().st_size, {"mid": mid, "status": "done" if ok else "failed",
                                    "as": "image", "uploaded": src.stat().st_size,
                                    "verify": why}

    if as_ == "video":
        try:
            tok = upload_media(path, "video")
            mid, err = wait_ready(e["caption"], tok, "video")
            if not mid:
                raise RuntimeError(f"POST video: {err}")
            time.sleep(0.4)
            ok, why = verify(mid, "video", None)
            if not ok:
                raise RuntimeError(f"video не сошлось: {why}")
            return path.stat().st_size, {"mid": mid, "status": "done", "as": "video",
                                         "uploaded": path.stat().st_size,
                                         "verify": why}
        except Exception as exc:  # noqa: BLE001
            # формат не принят как video — падаем на файл, оригинал важнее
            tok = upload_media(path, "file")
            mid, err = wait_ready(e["caption"], tok, "file")
            if not mid:
                raise RuntimeError(f"POST file после video ({exc}): {err}") from exc
            time.sleep(0.4)
            ok, why = verify(mid, "file", path)
            return path.stat().st_size, {"mid": mid,
                                         "status": "done" if ok else "failed",
                                         "as": "file", "fallback_from": "video",
                                         "uploaded": path.stat().st_size,
                                         "verify": why}

    tok = upload_media(path, "file")
    mid, err = wait_ready(e["caption"], tok, "file")
    if not mid:
        raise RuntimeError(f"POST file: {err}")
    time.sleep(0.4)
    ok, why = verify(mid, "file", path)
    return path.stat().st_size, {"mid": mid, "status": "done" if ok else "failed",
                                 "as": "file", "uploaded": path.stat().st_size,
                                 "verify": why}


def main() -> None:
    global JOURNAL, REPORT
    args = sys.argv[1:]
    plan_path = PLAN
    if "--plan" in args:
        plan_path = Path(args[args.index("--plan") + 1])
    if "--journal" in args:
        JOURNAL = Path(args[args.index("--journal") + 1])
    if "--report" in args:
        REPORT = Path(args[args.index("--report") + 1])
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 0
    start = int(args[args.index("--from") + 1]) if "--from" in args else 0
    year = int(args[args.index("--year") + 1]) if "--year" in args else None
    dry = "--dry-run" in args
    stop_on_error = "--stop-on-error" in args
    want_sha = "--sha" in args

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    entries = plan["entries"]
    done = journal_done()
    lines = [f"прогон: {now()}", f"план: {plan_path} ({plan.get('generated')})",
             f"постов в плане: {len(entries)}, уже сделано: {len(done)}"]
    if year is not None:
        lines.append(f"фильтр: только {year} год (каталоги и закреп — последним прогоном)")
    lines.append("")
    processed = failed = 0
    t0 = time.time()
    bytes_sent = 0

    for i, e in enumerate(entries):
        if i < start or i in done:
            continue
        if year is not None:
            # в режиме одного года каталоги и закреп не трогаем: они идут в конце ленты
            if e.get("year") != year or e["kind"] == "year_catalog":
                continue
        if limit and processed >= limit:
            break
        kind = e["kind"]
        missing = kind in ("file", "file_split") and not Path(e["path"]).exists()
        if dry:
            extra = f" as={e.get('as')}" if e.get("as") else ""
            if missing:
                extra += " (нет файла)"
            lines.append(f"[dry] {i} {kind}{extra} {e.get('path') or e['text'][:60]!r}")
            processed += 1
            continue
        if missing:
            journal_add({"i": i, "kind": kind, "status": "skipped",
                         "reason": "нет файла", "path": e["path"], "ts": now()})
            continue

        try:
            if kind == "file_split":
                sent, extra = upload_split(e)
                journal_add({"i": i, "kind": kind, "status": "done",
                             "path": e["path"], "bytes": e["bytes"],
                             "folder": e.get("folder"), "year": e.get("year"),
                             "sha256": extra["sha256"], "parts": extra["parts"],
                             "note_mid": extra["note_mid"], "ts": now()})
                processed += 1
                bytes_sent += sent
                continue

            if kind == "file":
                sent, rec = send_media(i, e, e.get("as", "file"))
                rec.update({"i": i, "kind": kind, "path": e["path"],
                            "bytes": e["bytes"], "folder": e.get("folder"),
                            "year": e.get("year"), "ts": now()})
                if want_sha:
                    rec["sha256"] = sha256_of(Path(e["path"]))
                journal_add(rec)
                if rec["status"] == "done":
                    processed += 1
                    bytes_sent += sent
                else:
                    failed += 1
                    lines.append(f"VERIFY FAIL {i} {e['path']}: {rec.get('verify')}")
                continue

            mid, err = post_message(e["text"])
            if not mid:
                raise RuntimeError(f"POST: {err}")
            if kind == "index_pin":
                api("PUT", f"/chats/{CHAT}/pin", {"message_id": mid})
            journal_add({"i": i, "kind": kind, "status": "done", "mid": mid,
                         "ts": now()})
            processed += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            journal_add({"i": i, "kind": kind, "status": "failed", "error": str(exc)[:300],
                         "path": e.get("path"), "ts": now()})
            lines.append(f"ERROR {i} {kind}: {str(exc)[:200]}")
            if stop_on_error:
                break
        finally:
            time.sleep(PAUSE)

        if processed % 50 == 0 and processed:
            spent = time.time() - t0
            lines.append(f"… {i}: сделано {processed}, ошибок {failed}, "
                         f"{bytes_sent / 2**20:.0f} МБ за {spent / 60:.0f} мин")

    spent = time.time() - t0
    lines += ["", f"итог: сделано {processed}, ошибок {failed}, "
                  f"{bytes_sent / 2**30:.2f} ГБ, {spent / 60:.1f} мин",
              f"всего в журнале: {len(journal_done())} из {len(entries)}"]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"ok: {processed} done, {failed} failed")


if __name__ == "__main__":
    main()
