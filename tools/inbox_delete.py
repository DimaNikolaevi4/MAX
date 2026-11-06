# -*- coding: utf-8 -*-
"""Удаление «входящих» из канала: всё, что новее последнего поста архива.

Граница — первый сверху пост архива («2011 · …», «Сканированные фото»).
Всё выше него считается «входящими» и удаляется, включая текстовые
объявления. Перед удалением сверяет, что каждое вложение уже сохранено на
диск (local/devices-manifest.json) — при расхождении останавливается.

  python tools/dump_channel.py            # обновить local/channel-dump.json
  python tools/inbox_delete.py            # только проверка, ничего не удаляет
  python tools/inbox_delete.py --yes      # проверить и удалить

Протокол: local/inbox-deleted.txt, копия удалённых сообщений —
local/inbox-deleted.json.
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
API = "https://platform-api2.max.ru"
TOKEN = json.loads((REPO / "local" / "tokens.json").read_text(encoding="utf-8"))["archive"]["token"]
CHAT = -80815063000413
DUMP = REPO / "local" / "channel-dump.json"
ARCHIVE = re.compile(r"^(\d{4} · |\*\*|Сканированные фото)")

if not DUMP.exists():
    raise SystemExit("нет local/channel-dump.json — сначала python tools/dump_channel.py")
rows = json.loads(DUMP.read_text(encoding="utf-8"))

cut = next((i for i, r in enumerate(rows)
            if ARCHIVE.match((r.get("text") or "").strip())), None)
if cut is None:
    raise SystemExit("СТОП: в дампе нет ни одного поста архива — граница не найдена")
inbox = rows[:cut]
if not inbox:
    print("ok nothing to delete")
    raise SystemExit(0)

man = json.loads((REPO / "local" / "devices-manifest.json").read_text(encoding="utf-8"))
man_mids = {v["mid"] for v in man.values()}
inbox_mids = {r["mid"] for r in inbox if r["atts"]}
missing = inbox_mids - man_mids
if missing:
    raise SystemExit(f"СТОП: {len(missing)} вложений не сохранены на диск: {sorted(missing)[:5]}")

lines = [f"граница: {rows[cut]['mid']} {(rows[cut]['text'] or '')[:40]!r}",
         f"к удалению: {len(inbox)} сообщений "
         f"(вложений {sum(len(r['atts']) for r in inbox)})", ""]
if "--yes" not in sys.argv:
    lines.append("режим проверки: добавьте --yes, чтобы удалить")
    for r in inbox:
        lines.append(f"БУДЕТ УДАЛЕНО {r['mid']} вложений={len(r['atts'])} "
                     f"{(r.get('text') or '')[:40]!r}")
    (REPO / "local" / "inbox-deleted.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"ok dry-run inbox={len(inbox)} (--yes to delete)")
    raise SystemExit(0)

(REPO / "local" / "inbox-deleted.json").write_text(
    json.dumps(inbox, ensure_ascii=False, indent=1), encoding="utf-8")

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
        lines.append(f"OK   {r['mid']}  вложений={len(r['atts'])}  "
                     f"{(r.get('text') or '')[:40]!r}")
    else:
        failed += 1
        lines.append(f"FAIL {r['mid']}  code={code}  {body[:160]}  "
                     f"{(r.get('text') or '')[:40]!r}")
    time.sleep(0.5)

lines += ["", f"удалено: {ok}, ошибок: {failed}"]
(REPO / "local" / "inbox-deleted.txt").write_text("\n".join(lines), encoding="utf-8")
print(f"ok deleted={ok} failed={failed}")
