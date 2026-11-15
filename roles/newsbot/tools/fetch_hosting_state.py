# -*- coding: utf-8 -*-
"""Забор состояния бота AI Now с хостинга на ПК (реестр + чёрный журнал).

После переезда на webhook реестр (pnews_registry.json) и чёрный журнал
(pnews_churn.jsonl) живут на хостинге (вне webroot: /0s3/bot1-data/).
Этот скрипт скачивает их по FTP в local/ — снимок 07:00 иdigest-инструменты
читают локальные копии. Чёрный журнал на ПК дополняется недостающими
строками (merge по дедупликации строк), реестр — заменяется.

Пароль FTP не хранится здесь: берётся из local/ftp-creds.json репозитория
cross-autoposting (тот же хостинг, тот же FTP-аккаунт mitiba_crossbot).

Запуск:  py roles\\newsbot\\tools\\fetch_hosting_state.py
"""
import ftplib
import json
import sys
from pathlib import Path

REPO = next(p for p in Path(__file__).resolve().parents
            if (p / ".git").exists())
LOCAL = REPO / "local"
CREDS = Path(r"E:\github\cross-autoposting\local\ftp-creds.json")
FTP_HOST = "mitiba.beget.tech"
# путь вне webroot от корня FTP
BASE = "/0s3/bot1-data"

creds = json.loads(CREDS.read_text(encoding="utf-8"))
ftp = ftplib.FTP(FTP_HOST, timeout=60)
ftp.login(creds["login"], creds["password"])
ftp.set_pasv(True)


def fetch(remote: str, local: Path, merge_lines: bool) -> None:
    buf = []
    ftp.retrlines(f"RETR {BASE}/{remote}", buf.append)
    remote_text = "\n".join(buf)
    if merge_lines and local.exists():
        known = set(local.read_text(encoding="utf-8").splitlines())
        extra = [ln for ln in remote_text.splitlines() if ln and ln not in known]
        if extra:
            with local.open("a", encoding="utf-8") as fh:
                fh.write("\n".join(extra) + "\n")
        print(f"{remote}: +{len(extra)} новых строк -> {local.name}")
    else:
        local.write_text(remote_text + ("\n" if remote_text else ""), encoding="utf-8")
        print(f"{remote}: скачан -> {local.name}")


fetch("pnews_registry.json", LOCAL / "pnews_registry.json", merge_lines=False)
fetch("pnews_churn.jsonl", LOCAL / "pnews_churn.jsonl", merge_lines=True)
ftp.quit()
print("ok")
