# -*- coding: utf-8 -*-
"""Пересчёт заголовков плана после удаления битых файлов.

Индексы записей не меняются (журнал заливки привязан к индексам): записи
удалённых файлов остаются в плане с пометкой skip, а тексты заголовков года,
папок, годовых каталогов и оглавления пересчитываются по уцелевшим файлам.
"""
import json
import sys
from collections import OrderedDict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
from archive_plan import files_phrase, folders_phrase, human, is_junk  # noqa: E402

PLAN = REPO / "local" / "archive-plan.json"
plan = json.loads(PLAN.read_text(encoding="utf-8"))
entries = plan["entries"]

for e in entries:
    if e["kind"] in ("file", "file_split"):
        e["skip"] = (not Path(e["path"]).exists()) or is_junk(e["path"])

years = OrderedDict()
cur_year = None
for e in entries:
    if e["kind"] == "year_header":
        cur_year = e["year"]
        years.setdefault(cur_year, OrderedDict())
    elif e["kind"] in ("file", "file_split"):
        years.setdefault(e["year"], OrderedDict())
        st = years[e["year"]].setdefault(e["folder"], [0, 0])
        if not e["skip"]:
            st[0] += 1
            st[1] += e["bytes"]


def folder_of_header(text: str, year: int) -> str:
    prefix = f"**{year} · "
    if text.startswith(prefix):
        return text[len(prefix):].rsplit("** —", 1)[0]
    return ""


for e in entries:
    if e["kind"] == "year_header":
        y = e["year"]
        folders = years[y]
        n_files = sum(v[0] for v in folders.values())
        n_bytes = sum(v[1] for v in folders.values())
        e["text"] = (f"**{y}** — {folders_phrase(len(folders))} · "
                     f"{files_phrase(n_files)} · {human(n_bytes)}")
    elif e["kind"] == "folder_header":
        y = e["year"]
        name = folder_of_header(e["text"], y)
        n_files, n_bytes = years[y].get(name, [0, 0])
        e["text"] = (f"**{y} · {name}** — {files_phrase(n_files)} · "
                     f"{human(n_bytes)}")
    elif e["kind"] == "year_catalog":
        y = e["year"]
        folders = years[y]
        n_files = sum(v[0] for v in folders.values())
        n_bytes = sum(v[1] for v in folders.values())
        lines = [f"**{y}** — {folders_phrase(len(folders))} · "
                 f"{files_phrase(n_files)} · {human(n_bytes)}", ""]
        for name, (n, b) in folders.items():
            lines.append(f"• {name} — {files_phrase(n)} · {human(b)}")
        text = "\n".join(lines)
        e["text"] = text[:3990] + "…" if len(text) > 4000 else text
    elif e["kind"] == "index_pin":
        index = ["**ОГЛАВЛЕНИЕ**", "",
                 "Архив изображений: фото и видео по годам и папкам.", ""]
        for y, folders in sorted(years.items()):
            n_files = sum(v[0] for v in folders.values())
            index.append(f"{y} — {folders_phrase(len(folders))} · {files_phrase(n_files)}")
        index += ["", "Сканированные фото — 25 файлов · 94,9 МБ (сразу после 2010)", ""]
        index += ["", "Как искать: в поиске канала наберите «2014 ·» — покажутся все посты "
                      "этого года; «2014 · 07.10.адлер» — конкретная папка.",
                  "", "Годовые каталоги — в конце ленты, после последнего года."]
        text = "\n".join(index)
        e["text"] = text[:3990] + "…" if len(text) > 4000 else text

PLAN.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")

skipped = sum(1 for e in entries if e.get("skip"))
lines = [f"пропущено (нет файла): {skipped}", ""]
for y, folders in sorted(years.items()):
    n_files = sum(v[0] for v in folders.values())
    n_bytes = sum(v[1] for v in folders.values())
    lines.append(f"{y}: {folders_phrase(len(folders))}, {files_phrase(n_files)}, "
                 f"{human(n_bytes)}")
(REPO / "local" / "plan-patched.txt").write_text("\n".join(lines), encoding="utf-8")
print(f"ok skipped={skipped}")
