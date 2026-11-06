# -*- coding: utf-8 -*-
"""Раскладка второй партии по годам с отбрасыванием дублей.

Правила:
  * пара внутри пачки, признанная копией, — оставляем файл большего размера
    (при равенстве — с меньшим photo_id, то есть более ранний в ленте);
  * совпадение с папкой «с телефонов и ноутбука» или с архивом — новый файл
    не нужен: в архиве лежит исходник большего разрешения;
  * «РАЗНЫЕ» (MAD > 8) — соседние кадры серии, оба остаются.

Итог: файлы в E:\\наши изображения\\с телефонов и ноутбука\\<год>,
манифест local/devices-manifest.json, протокол local/inbox2-applied.txt.
"""
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BATCH = sys.argv[sys.argv.index("--batch") + 1] if "--batch" in sys.argv else "inbox2"
DEST = Path(r"E:\наши изображения\с телефонов и ноутбука")
MANIFEST = REPO / "local" / f"{BATCH}-manifest.json"
DEV_MANIFEST = REPO / "local" / "devices-manifest.json"
VERIFY = REPO / "local" / f"{BATCH}-verify.json"
OUT = REPO / "local" / f"{BATCH}-applied.txt"

man = json.loads(MANIFEST.read_text(encoding="utf-8"))
items = list(man.values())
by_name = {v["name"]: v for v in items}
verify = json.loads(VERIFY.read_text(encoding="utf-8"))

skip = {}  # name -> причина


def pid(name: str) -> int:
    try:
        return int(name.split("_")[1].split(".")[0])
    except Exception:  # noqa: BLE001
        return 0


for pair in verify:
    if pair["verdict"] != "КОПИЯ":
        continue
    new = pair["name"]
    if pair["section"] == "batch":
        other_raw = pair["other"]
        for suf in (" (y=",):
            if suf in other_raw:
                other_raw = other_raw.split(suf)[0]
        other = other_raw
        a, b = by_name[new], by_name[other]
        if a["bytes"] != b["bytes"]:
            loser = new if a["bytes"] < b["bytes"] else other
        else:
            loser = new if pid(new) > pid(other) else other
        skip.setdefault(loser, "копия внутри пачки")
    else:
        skip.setdefault(new, f"уже есть ({pair['section']}): {pair['other']}")

# --- копирование ---
dev = json.loads(DEV_MANIFEST.read_text(encoding="utf-8")) if DEV_MANIFEST.exists() else {}
lines = []
copied = Counter()
bytes_copied = Counter()
skipped = Counter()
problems = []

for it in items:
    name = it["name"]
    if name in skip:
        skipped[it["year"]] += 1
        lines.append(f"ПРОПУСК y={it['year']} {name} — {skip[name]}")
        dev[f"skip:{it['mid']}:{name}"] = {
            "sha256": it["sha256"], "mid": it["mid"], "year": it["year"],
            "name": name, "source": it["type"], "bytes": it["bytes"],
            "skip": True, "reason": skip[name]}
        continue
    src = Path(it["path"])
    if not src.exists():
        problems.append(f"нет файла {src}")
        continue
    year_dir = DEST / str(it["year"])
    year_dir.mkdir(parents=True, exist_ok=True)
    dst = year_dir / name
    if not dst.exists() or dst.stat().st_size != src.stat().st_size:
        shutil.copy2(src, dst)
        copied[it["year"]] += 1
        bytes_copied[it["year"]] += dst.stat().st_size
    dev[str(dst)] = {"sha256": it["sha256"], "mid": it["mid"], "year": it["year"],
                     "name": name, "source": it["type"], "bytes": it["bytes"]}

DEV_MANIFEST.write_text(json.dumps(dev, ensure_ascii=False, indent=1), encoding="utf-8")

head = [f"всего в пачке: {len(items)}",
        f"скопировано: {sum(copied.values())}",
        f"пропущено дублей: {sum(skipped.values())}", ""]
for y in sorted({it["year"] for it in items}):
    head.append(f"{y}: скопировано {copied[y]}, пропущено {skipped[y]}, "
                f"{round(bytes_copied[y] / 2 ** 20, 1)} МБ")
head += ["", f"ошибок: {len(problems)}"]
head += problems
OUT.write_text("\n".join(head + ["", "--- пропуски ---"] + lines), encoding="utf-8")
print(f"ok copied={sum(copied.values())} skipped={sum(skipped.values())} errors={len(problems)}")
