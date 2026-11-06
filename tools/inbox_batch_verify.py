# -*- coding: utf-8 -*-
"""Точная проверка пар-кандидатов из local/inbox2-dedupe.txt.

dHash ловит и перекодированные копии, и соседние кадры серии. Здесь считаем
MAD (средняя абсолютная разница) по серому 128x128: у перекодированной копии
она < 3, у разных кадров — заметно больше.

Итог: local/inbox2-verify.txt + local/inbox2-verify.json
"""
import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageOps

REPO = Path(__file__).resolve().parent.parent
BATCH = sys.argv[sys.argv.index("--batch") + 1] if "--batch" in sys.argv else "inbox2"
DEDUPE = REPO / "local" / f"{BATCH}-dedupe.txt"
MANIFEST = REPO / "local" / f"{BATCH}-manifest.json"
OUT_TXT = REPO / "local" / f"{BATCH}-verify.txt"
OUT_JSON = REPO / "local" / f"{BATCH}-verify.json"
SIZE = 128

man = json.loads(MANIFEST.read_text(encoding="utf-8"))
by_name = {v["name"]: v for v in man.values()}

PAIR = re.compile(r"^\s+d=(\d+) (\S+) \(y=(\d{4})\) ~ (.+?)\s*$")
section = None
pairs = []
for line in DEDUPE.read_text(encoding="utf-8").splitlines():
    s = line.strip()
    if s.startswith("внутри пачки:"):
        section = "batch"
        continue
    if s.startswith("против папки"):
        section = "folder"
        continue
    if s.startswith("против архива:"):
        section = "archive"
        continue
    if s.startswith("===") or s.startswith("пар:") or s.startswith("совпадений:"):
        section = None
        continue
    m = PAIR.match(line)
    if m and section:
        pairs.append({"section": section, "d": int(m.group(1)),
                      "name": m.group(2), "year": int(m.group(3)),
                      "other": m.group(4)})


def gray(p: Path):
    with Image.open(p) as im:
        im = ImageOps.exif_transpose(im).convert("L").resize((SIZE, SIZE), Image.LANCZOS)
        return im


def mad(a: Path, b: Path):
    try:
        ga, gb = gray(a), gray(b)
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)
    pa, pb = list(ga.getdata()), list(gb.getdata())
    diff = sum(abs(x - y) for x, y in zip(pa, pb)) / len(pa)
    return round(diff, 2), None


def dims(p: Path):
    try:
        with Image.open(p) as im:
            return f"{im.width}x{im.height}"
    except Exception:  # noqa: BLE001
        return "?"


lines = [f"пар-кандидатов: {len(pairs)}", ""]
result = []
for it in pairs:
    new_path = Path(by_name[it["name"]]["path"]) if it["name"] in by_name else Path("")
    other_raw = re.sub(r"\s*\(y=\d{4}\)\s*$", "", it["other"])
    other = Path(by_name[other_raw]["path"]) if it["section"] == "batch" \
        else Path(other_raw)
    if not new_path.exists() or not other.exists():
        it["verdict"] = "нет файла"
        it["mad"] = None
        lines.append(f"[{it['section']}] {it['name']} — файл не найден")
        result.append(it)
        continue
    value, err = mad(new_path, other)
    it["mad"] = value
    it["dims_new"] = dims(new_path)
    it["dims_other"] = dims(other)
    it["bytes_new"] = new_path.stat().st_size
    it["bytes_other"] = other.stat().st_size
    if value is None:
        it["verdict"] = f"ошибка: {err}"
    elif value < 3:
        it["verdict"] = "КОПИЯ"
    elif value < 8:
        it["verdict"] = "ПОХОЖЕ"
    else:
        it["verdict"] = "РАЗНЫЕ"
    result.append(it)
    lines.append(f"[{it['section']:7s}] d={it['d']} MAD={value} "
                 f"{it['verdict']:8s} {it['name']} ({it['dims_new']}, "
                 f"{it['bytes_new'] // 1024}К) ~ {it['other']} "
                 f"({it['dims_other']}, {it['bytes_other'] // 1024}К)")

OUT_TXT.write_text("\n".join(lines), encoding="utf-8")
OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
counts = {}
for it in result:
    counts[it["verdict"]] = counts.get(it["verdict"], 0) + 1
print("ok", counts)
