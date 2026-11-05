# -*- coding: utf-8 -*-
"""Встраивает папку «с телефонов и ноутбука» в план по годам.

Файлы из E:\\наши изображения\\с телефонов и ноутбука\\<год> добавляются в
соответствующий год отдельной папкой «с телефонов и ноутбука». Годы 2017, 2019,
2020 в плане отсутствуют — для них создаётся новый блок года и годовой каталог.

Вставка идёт только после последнего залитого индекса (журнал заканчивается на
2010), поэтому существующие индексы журнала не сдвигаются.
"""
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
from archive_plan import files_phrase, human, media_kind, natural_key  # noqa: E402

PLAN = REPO / "local" / "archive-plan.json"
BACKUP = REPO / "local" / "archive-plan-before-devices.json"
SRC = Path(r"E:\наши изображения\с телефонов и ноутбука")
FOLDER = "с телефонов и ноутбука"

plan = json.loads(PLAN.read_text(encoding="utf-8"))
entries = plan["entries"]
cat_start = next(i for i, e in enumerate(entries) if e["kind"] == "year_catalog")

# --- блоки годов: (год, начало, конец) по year_header ---
starts = [i for i, e in enumerate(entries[:cat_start]) if e["kind"] == "year_header"]
blocks = []
for k, i in enumerate(starts):
    end = starts[k + 1] if k + 1 < len(starts) else cat_start
    blocks.append((entries[i]["year"], i, end))
have = {y for y, _s, _e in blocks}


def folder_block(year: int):
    """Заголовок папки + файлы этого года из новой папки."""
    src = SRC / str(year)
    files = sorted((p for p in src.iterdir() if p.is_file()),
                   key=lambda p: natural_key(p.name)) if src.is_dir() else []
    if not files:
        return [], 0
    total = sum(p.stat().st_size for p in files)
    out = [{"kind": "folder_header", "year": year,
            "text": f"**{year} · {FOLDER}** — {files_phrase(len(files))} · {human(total)}"}]
    for p in files:
        s = p.stat().st_size
        out.append({"kind": "file", "path": str(p), "bytes": s,
                    "as": media_kind(p, s), "caption": f"{year} · {FOLDER}",
                    "folder": FOLDER, "year": year})
    return out, total


def year_block(year: int):
    body, _total = folder_block(year)
    if not body:
        return []
    return [{"kind": "year_header", "year": year, "text": f"**{year}**"}] + body


targets = sorted({int(p.name) for p in SRC.iterdir() if p.is_dir() and p.name.isdigit()})
print("годы:", targets)

# --- куда вставлять ---
inserts = {}  # позиция -> список записей
for y in targets:
    if y in have:
        pos = next(e for yy, _s, e in blocks if yy == y)
        chunk, _t = folder_block(y)
        inserts.setdefault(pos, []).extend(chunk)
    else:
        pos = next((s for yy, s, _e in blocks if yy > y), cat_start)
        inserts.setdefault(pos, []).extend(year_block(y))

# внутри одной позиции — по возрастанию года
order = {}
for y in targets:
    order.setdefault(y, 0)

new_entries = []
for i, e in enumerate(entries):
    if i in inserts:
        new_entries.extend(inserts[i])
    new_entries.append(e)
if cat_start == len(entries):
    pass

# --- годовые каталоги для новых годов ---
new_years = [y for y in targets if y not in have]
if new_years:
    cat_pos = {}
    for i, e in enumerate(new_entries):
        if e["kind"] == "year_catalog":
            cat_pos[e["year"]] = i
    for y in new_years:
        pos = next((cat_pos[yy] for yy in sorted(cat_pos) if yy > y), None)
        if pos is None:
            pos = max(cat_pos.values()) + 1 if cat_pos else len(new_entries)
        new_entries.insert(pos, {"kind": "year_catalog", "year": y, "text": f"**{y}**"})
        # пересобрать позиции после вставки
        cat_pos = {e["year"]: i for i, e in enumerate(new_entries)
                   if e["kind"] == "year_catalog"}

shutil.copyfile(PLAN, BACKUP)
plan["entries"] = new_entries
PLAN.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")

added = sum(1 for e in new_entries if e["kind"] == "file" and e.get("folder") == FOLDER)
print(f"ok entries={len(new_entries)} added_files={added} new_years={new_years}")
