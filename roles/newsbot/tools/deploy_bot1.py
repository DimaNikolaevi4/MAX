# -*- coding: utf-8 -*-
"""Деплой и проверка webhook-обработчика bot1 (секреты НЕ печатаются).

Команды:
  py roles\\newsbot\\tools\\deploy_bot1.py upload [remote]     # залить рабочий
                                                             # файл (по умолчанию
                                                             # bot1_webhook_v2.php)
  py roles\\newsbot\\tools\\deploy_bot1.py post [remote] [type] [chat] [text]
                                                             # POST события на
                                                             # удалённый файл
  py roles\\newsbot\\tools\\deploy_bot1.py log [n]             # хвост журнала
  py roles\\newsbot\\tools\\deploy_bot1.py check403           # GET без секрета
  py roles\\newsbot\\tools\\deploy_bot1.py subs               # подписка (URL
                                                             # с замаскированным
                                                             # секретом)
  py roles\\newsbot\\tools\\deploy_bot1.py switch             # старое -> вне
                                                             # webroot, v2 ->
                                                             # bot1_webhook.php

FTP-доступ (логин/пароль) — E:\\github\\cross-autoposting\\local\\ftp-creds.json.
"""
import ftplib
import json
import re
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = next(p for p in Path(__file__).resolve().parents
            if (p / ".git").exists())
PHP = REPO / "local" / "hosting" / "bot1_webhook.php"
FTP_CREDS = Path(r"E:\github\cross-autoposting\local\ftp-creds.json")
FTP_HOST = "mitiba.beget.tech"
REMOTE_DIR = "/0s3/public_html/bot1"
DATA_DIR = "/0s3/bot1-data"
PUBLIC = "https://0s3.ru/bot1"
API = "https://platform-api2.max.ru"
CA = REPO / "local" / "russian_ca_bundle.pem"


def secret() -> str:
    return re.search(r"const SECRET\s*=\s*'([^']+)'",
                     PHP.read_text(encoding="utf-8")).group(1)


def token() -> str:
    return json.loads((REPO / "local" / "tokens.json").read_text(
        encoding="utf-8"))["newsbot"]["token"]


def mask(url: str) -> str:
    return re.sub(r"s=([^&]{4})[^&]*", r"s=\1…", url)


def ftp_open() -> ftplib.FTP:
    c = json.loads(FTP_CREDS.read_text(encoding="utf-8"))
    ftp = ftplib.FTP(FTP_HOST, timeout=60)
    ftp.login(c["login"], c["password"])
    ftp.set_pasv(True)
    return ftp


def ctx() -> ssl.SSLContext:
    c = ssl.create_default_context()
    if CA.exists():
        c.load_verify_locations(cafile=str(CA))
    return c


def upload(remote: str) -> None:
    ftp = ftp_open()
    try:
        ftp.cwd(REMOTE_DIR)
        with PHP.open("rb") as fh:
            ftp.storbinary(f"STOR {remote}", fh)
        print(f"upload ok: {remote} ({ftp.size(remote)} байт)")
    finally:
        ftp.quit()


def post(remote: str, utype: str, chat: int, text: str) -> None:
    upd = {"update_type": utype, "chat_id": chat,
           "user": {"user_id": chat, "name": "владелец"}}
    if utype in ("message_created", "message_edited"):
        upd["message"] = {
            "recipient": {"chat_type": "dialog", "chat_id": chat},
            "sender": {"user_id": chat, "is_bot": False},
            "body": {"mid": f"deploy.{utype}", "text": text or "тест"},
        }
    if utype.startswith("comment_"):
        upd["message"] = {
            "recipient": {"chat_type": "chat", "chat_id": chat,
                          "post_id": "deploy.test"},
            "sender": {"user_id": 900001, "is_bot": False,
                       "first_name": "Тест"},
            "body": {"mid": f"deploy.{utype}", "text": text},
        }
    req = urllib.request.Request(
        f"{PUBLIC}/{remote}", data=json.dumps(upd, ensure_ascii=False).encode(),
        method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "curl/8.13.0")
    req.add_header("X-Max-Bot-Api-Secret", secret())
    try:
        with urllib.request.urlopen(req, context=ctx(), timeout=30) as r:
            print("POST -> HTTP", r.status, r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print("POST FAIL -> HTTP", e.code,
              (e.read() or b"").decode("utf-8", "replace")[:200])
        raise SystemExit(1)


def log_tail(n: int) -> None:
    ftp = ftp_open()
    try:
        buf = []
        ftp.retrbinary(f"RETR {DATA_DIR}/bot1_webhook.log",
                       lambda chunk: buf.append(chunk))
        raw = b"".join(buf)
        text = raw.decode("utf-8", "replace")
        lines = text.splitlines()[-n:]
        print("\n".join(lines))
        print(f"(строк: {len(lines)}, размер: {len(raw)} байт)")
        bad = 0
        for line in text.splitlines()[-n:]:
            try:
                line.encode("utf-8").decode("utf-8")
            except Exception:
                bad += 1
        print("невалидных UTF-8 строк в хвосте:", bad)
    finally:
        ftp.quit()


def check403() -> None:
    req = urllib.request.Request(f"{PUBLIC}/bot1_webhook.php", method="GET")
    req.add_header("User-Agent", "curl/8.13.0")
    try:
        with urllib.request.urlopen(req, context=ctx(), timeout=30) as r:
            print("без секрета -> HTTP", r.status, "(ожидалось 403!)")
    except urllib.error.HTTPError as e:
        print("без секрета -> HTTP", e.code)


def subs() -> None:
    req = urllib.request.Request(API + "/subscriptions")
    req.add_header("Authorization", token())
    req.add_header("User-Agent", "curl/8.13.0")
    with urllib.request.urlopen(req, context=ctx(), timeout=30) as r:
        data = json.loads(r.read().decode("utf-8"))
    for s in data.get("subscriptions") or []:
        print("подписка:", mask(s.get("url", "")))


def switch() -> None:
    ftp = ftp_open()
    try:
        ftp.cwd(REMOTE_DIR)
        # старое — ВНЕ webroot (в webroot бэкап с секретом отдаётся как текст)
        try:
            ftp.rename("bot1_webhook.php",
                       f"{DATA_DIR}/bot1_webhook_prev.php")
        except ftplib.error_perm as e:
            if "550" not in str(e):
                raise
        ftp.rename("bot1_webhook_v2.php", "bot1_webhook.php")
        print("switch ok: старый -> bot1-data/bot1_webhook_prev.php, "
              "v2 -> bot1_webhook.php")
        print("файлы в каталоге:", sorted(ftp.nlst()))
    finally:
        ftp.quit()


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "upload":
        upload(sys.argv[2] if len(sys.argv) > 2 else "bot1_webhook_v2.php")
    elif cmd == "post":
        remote = sys.argv[2] if len(sys.argv) > 2 else "bot1_webhook_v2.php"
        utype = sys.argv[3] if len(sys.argv) > 3 else "bot_stopped"
        chat = int(sys.argv[4]) if len(sys.argv) > 4 else 537566305
        text = sys.argv[5] if len(sys.argv) > 5 else ""
        post(remote, utype, chat, text)
    elif cmd == "log":
        log_tail(int(sys.argv[2]) if len(sys.argv) > 2 else 8)
    elif cmd == "check403":
        check403()
    elif cmd == "subs":
        subs()
    elif cmd == "switch":
        switch()
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
