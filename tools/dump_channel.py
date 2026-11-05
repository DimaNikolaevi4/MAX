# -*- coding: utf-8 -*-
"""Дамп последних сообщений канала-архива: отправитель, текст, вложения."""
import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
API = "https://platform-api2.max.ru"
TOKEN = json.loads((REPO / "local" / "tokens.json").read_text(encoding="utf-8"))["archive"]["token"]
CHAT = -80815063000413
OUT = REPO / "local" / "channel-dump.json"

msgs, to = [], None
for _ in range(40):
    path = f"/messages?chat_id={CHAT}&count=100"
    if to is not None:
        path += f"&to={to}"
    r = subprocess.run(["curl.exe", "-s", "-H", f"Authorization: {TOKEN}", API + path],
                       capture_output=True)
    try:
        batch = json.loads((r.stdout or b"").decode("utf-8", errors="replace")).get("messages") or []
    except Exception:  # noqa: BLE001
        break
    if not batch:
        break
    msgs += batch
    oldest = min((m.get("timestamp") or 0) for m in batch)
    if to is not None and oldest >= to:
        break
    to = oldest - 1
    if len(batch) < 100:
        break

rows = []
for m in msgs:
    b = m.get("body") or {}
    sender = m.get("sender") or {}
    atts = []
    for a in b.get("attachments") or []:
        p = a.get("payload") or {}
        atts.append({"type": a.get("type"), "url": p.get("url"),
                     "filename": a.get("filename"), "size": a.get("size"),
                     "photo_id": p.get("photo_id"), "duration": a.get("duration"),
                     "width": p.get("width"), "height": p.get("height")})
    rows.append({"mid": b.get("mid"), "ts": m.get("timestamp"),
                 "sender_id": sender.get("user_id"), "sender_name": sender.get("name"),
                 "text": (b.get("text") or "")[:200], "atts": atts})

OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"ok messages={len(rows)}")
