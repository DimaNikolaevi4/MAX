# -*- coding: utf-8 -*-
"""Планировщик наполнения канала-архива MAX: файлы как есть, 1 файл = 1 пост.

Использование:
  python tools/archive_plan.py [--out local/archive-plan.json]

Что делает:
  * обходит E:\\наши изображения\\мои и E:\\наши изображения\\камера;
  * определяет год папки: из имени -> медиана EXIF-дат фото -> даты файлов;
  * раскладывает всё в хронологию 2006 -> 2026:
      заголовок года, заголовки папок, по одному посту на файл;
      файлы из корня -> группа «Разное <год>»;
      папка «камера» -> группы «камера <год>»;
  * в конце — годовые каталоги и закреплённое оглавление;
  * пишет план в JSON (его исполняет tools/archive_upload.py) и отчёт.

Служебный мусор (Thumbs.db, *.db, *.cfg, *.info) пропускается.
Файлы больше 4 ГБ в план не попадают — они в списке «нужно решение».
"""
import datetime
import json
import os
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    Image = None

REPO = Path(__file__).resolve().parent.parent
MOI = Path(r"E:\наши изображения\мои")
CAMERA = Path(r"E:\наши изображения\камера")
OUT_JSON = REPO / "local" / "archive-plan.json"
OUT_TXT = REPO / "local" / "archive-plan.txt"
LIMIT = 4 * 1024**3  # лимит MAX на файл типа `file`
JUNK_EXT = {".db", ".cfg", ".info"}
MONTHS = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6,
    "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
}

Y4 = re.compile(r"(?<!\d)(19[5-9]\d|20[0-2]\d)(?!\d)")
D_M_Y = re.compile(r"(?<!\d)(\d{1,2})[.\s,_-](\d{1,2})[.\s,_-](\d{2,4})(?!\d)")
Y_M_D = re.compile(r"(?<!\d)(19\d{2}|20[0-2]\d)[-.\s](\d{1,2})[-.\s](\d{1,2})(?!\d)")


def is_junk(name: str) -> bool:
    return name.lower() == "thumbs.db" or Path(name).suffix.lower() in JUNK_EXT


def year_from_name(name: str):
    m = Y4.search(name)
    if m:
        return int(m.group(1))
    m = D_M_Y.search(name)
    if m:
        yy = int(m.group(3))
        if yy < 100:
            return 2000 + yy if yy <= 30 else 1900 + yy
        return yy
    return None


def date_from_name(name: str):
    """Пытается вытащить дату события из имени папки: (год, месяц, день) или None."""
    m = Y_M_D.search(name)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    m = D_M_Y.search(name)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y = 2000 + y if y <= 30 else 1900 + y
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return y, mo, d
    low = name.lower()
    for stem, mo in MONTHS.items():
        if stem in low:
            y = year_from_name(name)
            if y:
                return y, mo, 15
    return None


def exif_date(p: Path):
    if Image is None:
        return None
    try:
        with Image.open(p) as im:
            ex = im.getexif()
            dt = str(ex.get(36867) or ex.get(306) or "")
        if len(dt) >= 10 and dt[:4].isdigit():
            return datetime.datetime(int(dt[:4]), int(dt[5:7]), int(dt[8:10]))
    except Exception:  # noqa: BLE001
        return None
    return None


def scan_folder(folder: Path):
    """Файлы папки: список (путь, размер), суммарный размер, даты."""
    files, total, dates = [], 0, []
    for dp, _dn, fn in os.walk(folder):
        for f in sorted(fn):
            if is_junk(f):
                continue
            p = Path(dp) / f
            try:
                s = p.stat().st_size
            except OSError:
                continue
            files.append((p, s))
            total += s
            d = exif_date(p) if p.suffix.lower() in (".jpg", ".jpeg") else None
            if d is None:
                d = datetime.datetime.fromtimestamp(p.stat().st_mtime)
            dates.append(d)
    files.sort(key=lambda x: natural_key(x[0].name))
    return files, total, dates


def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def human(size: int) -> str:
    for unit, div in (("ГБ", 1024**3), ("МБ", 1024**2), ("КБ", 1024)):
        if size >= div:
            return f"{size / div:.1f} {unit}".replace(".0 ", " ").replace(".", ",")
    return f"{size} Б"


def plural(n: int, one: str, few: str, many: str) -> str:
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        return few
    return many


def files_phrase(n: int) -> str:
    return f"{n} {plural(n, 'файл', 'файла', 'файлов')}"


def folders_phrase(n: int) -> str:
    return f"{n} {plural(n, 'папка', 'папки', 'папок')}"


def main() -> None:
    out_json = OUT_JSON
    if "--out" in sys.argv:
        out_json = Path(sys.argv[sys.argv.index("--out") + 1])

    groups = defaultdict(list)  # year -> список групп
    oversized = []

    # --- папки и файлы из корня «мои» ---
    loose = defaultdict(list)
    for name in sorted(os.listdir(MOI)):
        p = MOI / name
        if p.is_dir():
            files, total, dates = scan_folder(p)
            if not files:
                continue
            y = year_from_name(name)
            d = date_from_name(name)
            if y is None:
                years = [x.year for x in dates]
                y = int(statistics.median(years)) if years else 0
            if d is None:
                d = (min(dates).year, min(dates).month, min(dates).day) if dates else (y, 12, 31)
            key = datetime.datetime(d[0], max(1, min(12, d[1])), max(1, min(28, d[2])))
            groups[y].append({"kind": "folder", "name": name, "path": str(p),
                              "files": files, "bytes": total, "key": key.isoformat()})
        else:
            if is_junk(name):
                continue
            s = p.stat().st_size
            y = year_from_name(name) or datetime.datetime.fromtimestamp(
                p.stat().st_mtime).year
            loose[y].append((p, s))

    for y, items in loose.items():
        files = sorted(items, key=lambda x: natural_key(x[0].name))
        key = min(datetime.datetime.fromtimestamp(p.stat().st_mtime) for p, _ in files)
        groups[y].append({"kind": "loose", "name": "Разное", "path": str(MOI),
                          "files": files, "bytes": sum(s for _, s in files),
                          "key": key.isoformat()})

    # --- камера ---
    cam = defaultdict(list)
    for f in sorted(os.listdir(CAMERA)):
        p = CAMERA / f
        if not p.is_file() or is_junk(f):
            continue
        y = year_from_name(f) or datetime.datetime.fromtimestamp(p.stat().st_mtime).year
        cam[y].append((p, p.stat().st_size))
    for y, items in cam.items():
        files = sorted(items, key=lambda x: natural_key(x[0].name))
        key = min(datetime.datetime.fromtimestamp(p.stat().st_mtime) for p, _ in files)
        groups[y].append({"kind": "camera", "name": "камера", "path": str(CAMERA),
                          "files": files, "bytes": sum(s for _, s in files),
                          "key": key.isoformat()})

    # --- сборка плана ---
    entries, catalog = [], {}
    for y in sorted(groups):
        glist = sorted(groups[y], key=lambda g: (g["key"], natural_key(g["name"])))
        n_files = sum(len(g["files"]) for g in glist)
        n_bytes = sum(g["bytes"] for g in glist)
        entries.append({"kind": "year_header",
                        "text": f"**{y}** — {folders_phrase(len(glist))} · "
                                f"{files_phrase(n_files)} · {human(n_bytes)}"})
        catalog[y] = {"folders": len(glist), "files": n_files, "bytes": n_bytes, "items": []}
        for g in glist:
            kept = []
            for p, s in g["files"]:
                if s > LIMIT:
                    oversized.append((p, s))
                else:
                    kept.append((p, s))
            g["files"] = kept
            g["bytes"] = sum(s for _, s in kept)
            if not g["files"]:
                continue
            entries.append({"kind": "folder_header",
                            "text": f"**{y} · {g['name']}** — "
                                    f"{files_phrase(len(g['files']))} · {human(g['bytes'])}"})
            catalog[y]["items"].append({"name": g["name"], "files": len(g["files"]),
                                        "bytes": g["bytes"]})
            for p, s in g["files"]:
                entries.append({"kind": "file", "path": str(p), "bytes": s,
                                "caption": f"{y} · {g['name']}",
                                "folder": g["name"], "year": y})

    # --- годовые каталоги и оглавление ---
    for y in sorted(catalog):
        c = catalog[y]
        lines = [f"**{y}** — {folders_phrase(c['folders'])} · {files_phrase(c['files'])} · "
                 f"{human(c['bytes'])}", ""]
        for it in c["items"]:
            lines.append(f"• {it['name']} — {files_phrase(it['files'])} · {human(it['bytes'])}")
        text = "\n".join(lines)
        if len(text) > 4000:
            text = text[:3990] + "…"
        entries.append({"kind": "year_catalog", "year": y, "text": text})

    index = ["**ОГЛАВЛЕНИЕ**", "",
             "Архив изображений: файлы как есть, по годам и папкам.", ""]
    for y in sorted(catalog):
        c = catalog[y]
        index.append(f"{y} — {folders_phrase(c['folders'])} · {files_phrase(c['files'])}")
    index += ["", "Как искать: в поиске канала наберите «2014 ·» — покажутся все посты "
                  "этого года; «2014 · 07.10.адлер» — конкретная папка.",
              "", "Годовые каталоги — в конце ленты, после последнего года."]
    text = "\n".join(index)
    if len(text) > 4000:
        text = text[:3990] + "…"
    entries.append({"kind": "index_pin", "text": text})

    plan = {"generated": datetime.datetime.now().isoformat(timespec="seconds"),
            "entries": entries}
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")

    # --- отчёт ---
    rep = [f"план: {out_json}", f"постов: {len(entries)}",
           f"файлов: {sum(1 for e in entries if e['kind'] == 'file')}",
           f"объём: {human(sum(e.get('bytes', 0) for e in entries if e['kind'] == 'file'))}", ""]
    for y in sorted(catalog):
        c = catalog[y]
        rep.append(f"{y}: {folders_phrase(c['folders'])}, {files_phrase(c['files'])}, "
                   f"{human(c['bytes'])}")
    if oversized:
        rep.append("")
        rep.append("НЕ ВЛЕЗАЮТ (больше 4 ГБ, нужно решение):")
        for p, s in oversized:
            rep.append(f"  {human(s)}  {p}")
    OUT_TXT.write_text("\n".join(rep), encoding="utf-8")
    print(f"ok: {len(entries)} entries -> {out_json}")


if __name__ == "__main__":
    main()
