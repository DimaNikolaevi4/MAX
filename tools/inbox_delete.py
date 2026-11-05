# -*- coding: utf-8 -*-
"""Удаление «входящих» из канала: всё новее объявления + само объявление.

Перед удалением сверяет, что каждое вложение уже сохранено на диск
(local/devices-manifest.json) — при расхождении останавливается.

  python tools/inbox_delete.py            # только проверка, ничего не удаляет
  python tools/inbox_delete.py --yes      # проверить и удалить

Протокол: local/inbox-deleted.txt, копия удалённых сообщений —
local/inbox-deleted.json.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
API = "https://platform-api2.max.ru"
TOKEN = json.loads((REPO / "local" / "tokens.json").read_text(encoding="utf-8"))["archive"]["token"]
CHAT = -80815063000413
MARK = "переместить с других устройств"

msgs, marker = [], None
for _ in range(8):
    path = f"/messages?chat_id={CHAT}&count=100"
    if marker:
        path += f"&from={marker}"
    r = subprocess.run(["curl.exe", "-s", "-H", f"Authorization: {TOKEN}", API + path],
                       capture_output=True)
    try:
        batch = json.loads((r.stdout or b"").decode("utf-8", errors="replace")).get("messages") or []
    except Exception:  # noqa: BLE001
        break
    if not batch:
        break
    msgs += batch
    marker = (batch[-1].get("body") or {}).get("mid")
    if len(batch) < 100:
        break

rows = []
for m in msgs:
    b = m.get("body") or {}
    rows.append({"mid": b.get("mid"), "ts": m.get("timestamp"),
                 "text": b.get("text") or "",
                 "atts": b.get("attachments") or []})

idx = next((i for i, r in enumerate(rows) if MARK in r["text"].lower()), None)
if idx is None:
    (REPO / "local" / "inbox-deleted.txt").write_text(
        "входящих нет: объявление не найдено, удалять нечего", encoding="utf-8")
    print("ok nothing to delete")
    raise SystemExit(0)
inbox = rows[:idx + 1]

man = json.loads((REPO / "local" / "devices-manifest.json").read_text(encoding="utf-8"))
man_mids = {v["mid"] for v in man.values()}
inbox_mids = {r["mid"] for r in inbox if r["atts"]}
missing = inbox_mids - man_mids
if missing:
    raise SystemExit(f"СТОП: {len(missing)} вложений не сохранены на диск: {sorted(missing)[:5]}")

(REPO / "local" / "inbox-deleted.json").write_text(
    json.dumps(inbox, ensure_ascii=False, indent=1), encoding="utf-8")

lines = [f"к удалению: {len(inbox)} сообщений", ""]
if "--yes" not in sys.argv:
    lines.append("режим проверки: добавьте --yes, чтобы удалить")
    for r in inbox:
        lines.append(f"БУДЕТ УДАЛЕНО {r['mid']} вложений={len(r['atts'])} {r['text'][:40]!r}")
    (REPO / "local" / "inbox-deleted.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"ok dry-run inbox={len(inbox)} (--yes to delete)")
    raise SystemExit(0)

ok = failed = 0
for r in inbox:
    body, code = "", ""
    for attempt in range(3):
        p = subprocess.run(["curl.exe", "-s", "-X", "DELETE", "-w", "\n%{http_code}",
                            "-H", f"Authorization: {TOKEN}",
                            f"{API}/messages?chat_id={CHAT}&message_id={r['mid']}"],
                           capture_output=True, timeout=120)
        out = (p.stdout or b"").decode("utf-8", errors="replace")
        body, code = (out.rsplit("\n", 1) + [""])[:2] if "\n" in out else (out, "")
        if code.strip() in ("200", "204"):
            break
        time.sleep(1.5 * (attempt + 1))
    if code.strip() in ("200", "204"):
        ok += 1
        lines.append(f"OK   {r['mid']}  вложений={len(r['atts'])}  {r['text'][:40]!r}")
    else:
        failed += 1
        lines.append(f"FAIL {r['mid']}  code={code}  {body[:160]}  {r['text'][:40]!r}")
    time.sleep(0.5)

lines += ["", f"удалено: {ok}, ошибок: {failed}"]
(REPO / "local" / "inbox-deleted.txt").write_text("\n".join(lines), encoding="utf-8")
print(f"ok deleted={ok} failed={failed}")
