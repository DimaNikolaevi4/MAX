# -*- coding: utf-8 -*-
"""Исполнение плана наполнения канала-архива MAX.

Использование:
  python tools/archive_upload.py [--plan local/archive-plan.json] [--limit N]
                                 [--from I] [--dry-run] [--sha] [--stop-on-error]

Что делает:
  * читает план из tools/archive_plan.py (local/archive-plan.json);
  * постит по порядку: заголовки, файлы как `type=file` (байт-в-байт),
    годовые каталоги, закрепляемое оглавление;
  * каждый успешный пост пишет в журнал local/archive-journal.jsonl —
    повторный запуск продолжает с места остановки (докачка);
  * после каждого поста GET-контроль: вложение на месте, имя и размер совпали;
  * соблюдает лимит 2 сообщения/сек, повторяет отправку при
    `attachment.not.ready` с растущим интервалом;
  * ошибки не роняют прогон: пост помечается failed и остаётся в очереди.

Отчёт: local/archive-run.txt (UTF-8). Консоль — только ASCII.
"""
import json
import os
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
PAUSE = 0.65          # лимит 2 сообщения/сек на канал
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


def upload_file(path: Path):
    """Возвращает токен вложения или бросает исключение."""
    last = ""
    for attempt in range(3):
        body, code = api("POST", "/uploads?type=file")
        try:
            up_url = json.loads(body)["url"]
        except Exception:  # noqa: BLE001
            last = f"/uploads {code}: {body[:160]}"
            time.sleep(2 * (attempt + 1))
            continue
        body2, code2 = curl(["-X", "POST", "-F", f"data=@{path}", up_url])
        try:
            tok = json.loads(body2).get("token", "")
        except Exception:  # noqa: BLE001
            tok = ""
        if tok:
            return tok
        last = f"upload {code2}: {body2[:160]}"
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(last or "upload failed")


def post_message(text: str, attachment_token: str | None = None):
    payload = {"text": text, "format": "markdown", "notify": True}
    if attachment_token:
        payload["attachments"] = [{"type": "file", "payload": {"token": attachment_token}}]
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


def wait_ready(text: str, token: str):
    """Отправка с повтором при attachment.not.ready."""
    mid, err = post_message(text, token)
    for delay in READY_DELAYS:
        if mid or "attachment.not.ready" not in err:
            return mid, err
        time.sleep(delay)
        mid, err = post_message(text, token)
    return mid, err


def verify(mid: str, path: Path | None):
    body, _code = api("GET", f"/messages/{mid}")
    try:
        msg = json.loads(body)
    except Exception:  # noqa: BLE001
        return False, "GET не JSON"
    if not path:
        return True, ""
    atts = (msg.get("body") or {}).get("attachments") or []
    if not atts:
        return False, "нет вложения"
    a = atts[0]
    size = a.get("size")
    name = a.get("filename")
    ok = size == path.stat().st_size and name == path.name
    return ok, f"size={size} name={name!r}"


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
        if e.get("status") == "done":
            done[e["i"]] = e
    return done


def main() -> None:
    args = sys.argv[1:]
    plan_path = PLAN
    if "--plan" in args:
        plan_path = Path(args[args.index("--plan") + 1])
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 0
    start = int(args[args.index("--from") + 1]) if "--from" in args else 0
    dry = "--dry-run" in args
    stop_on_error = "--stop-on-error" in args
    want_sha = "--sha" in args

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    entries = plan["entries"]
    done = journal_done()
    lines = [f"прогон: {now()}", f"план: {plan_path} ({plan.get('generated')})",
             f"постов в плане: {len(entries)}, уже сделано: {len(done)}", ""]
    processed = failed = 0
    t0 = time.time()
    bytes_sent = 0

    for i, e in enumerate(entries):
        if i < start or i in done:
            continue
        if limit and processed >= limit:
            break
        kind = e["kind"]
        if dry:
            lines.append(f"[dry] {i} {kind} {e.get('path') or e['text'][:60]!r}")
            processed += 1
            continue

        try:
            if kind == "file":
                path = Path(e["path"])
                if not path.exists():
                    journal_add({"i": i, "kind": kind, "status": "failed",
                                 "error": "нет файла", "path": str(path), "ts": now()})
                    failed += 1
                    lines.append(f"FAIL {i}: нет файла {path}")
                    continue
                tok = upload_file(path)
                mid, err = wait_ready(e["caption"], tok)
                if not mid:
                    raise RuntimeError(f"POST: {err}")
                time.sleep(0.4)
                ok, why = verify(mid, path)
                rec = {"i": i, "kind": kind, "status": "done" if ok else "failed",
                       "mid": mid, "path": str(path), "bytes": e["bytes"],
                       "folder": e.get("folder"), "year": e.get("year"),
                       "verify": why, "ts": now()}
                if want_sha:
                    import hashlib
                    h = hashlib.sha256()
                    with open(path, "rb") as f:
                        for chunk in iter(lambda: f.read(4 << 20), b""):
                            h.update(chunk)
                    rec["sha256"] = h.hexdigest()
                journal_add(rec)
                if ok:
                    processed += 1
                    bytes_sent += e["bytes"]
                else:
                    failed += 1
                    lines.append(f"VERIFY FAIL {i} {path.name}: {why}")
            else:
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
