# -*- coding: utf-8 -*-
"""Добавляет в план только новые файлы папки «с телефонов и ноутбука».

Повторный запуск безопасен: уже включённые в план пути пропускаются.
Вставка идёт в конец папки «с телефонов и ноутбука» своего года (для 2024 и
2025 папки ещё нет — создаётся заголовок в конце блока года), то есть заведомо
после последнего залитого индекса журнала.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / ".git").exists())))
from shared.paths import REPO  # noqa: E402
sys.path.insert(0, str(REPO / "tools"))
from archive_plan import files_phrase, human, media_kind, natural_key  # noqa: E402

PLAN = REPO / "local" / "archive-plan.json"
SRC = Path(r"E:\наши изображения\с телефонов и ноутбука")
FOLDER = "с телефонов и ноутбука"

plan = json.loads(PLAN.read_text(encoding="utf-8"))
entries = plan["entries"]
cat_start = next(i for i, e in enumerate(entries) if e["kind"] == "year_catalog")

have_paths = {str(Path(e["path"])) for e in entries if e.get("folder") == FOLDER}
starts = [i for i, e in enumerate(entries[:cat_start]) if e["kind"] == "year_header"]
blocks = {}
for k, i in enumerate(starts):
    end = starts[k + 1] if k + 1 < len(starts) else cat_start
    blocks[entries[i]["year"]] = (i, end)

targets = sorted(int(p.name) for p in SRC.iterdir() if p.is_dir() and p.name.isdigit())
inserts = {}
added = 0
for y in targets:
    src = SRC / str(y)
    files = sorted((p for p in src.iterdir() if p.is_file()),
                   key=lambda p: natural_key(p.name))
    new = [p for p in files if str(p) not in have_paths]
    if not new or y not in blocks:
        continue
    start, end = blocks[y]
    body = []
    has_folder = any(entries[i].get("folder") == FOLDER
                     for i in range(start, end))
    if not has_folder:
        total = sum(p.stat().st_size for p in files)
        body.append({"kind": "folder_header", "year": y,
                     "text": f"**{y} · {FOLDER}** — {files_phrase(len(files))} · {human(total)}"})
        pos = end
    else:
        pos = max(i for i in range(start, end)
                  if entries[i].get("folder") == FOLDER) + 1
    for p in new:
        s = p.stat().st_size
        body.append({"kind": "file", "path": str(p), "bytes": s,
                     "as": media_kind(p, s), "caption": f"{y} · {FOLDER}",
                     "folder": FOLDER, "year": y})
    inserts.setdefault(pos, []).extend(body)
    added += len(new)

new_entries = []
for i, e in enumerate(entries):
    if i in inserts:
        new_entries.extend(inserts[i])
    new_entries.append(e)
if cat_start == len(entries):
    new_entries.extend(inserts.get(cat_start, []))

plan["entries"] = new_entries
PLAN.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
print(f"ok added={added} entries={len(new_entries)}")
