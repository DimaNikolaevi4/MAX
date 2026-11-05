# -*- coding: utf-8 -*-
"""Проверка новых входящих на дубли по всему компьютеру.

Слои:
  1) sha256 внутри пачки, против папки «с телефонов и ноутбука» и против
     архива (мои, камера) — с предфильтром по размеру;
  2) dHash (похожесть картинки) внутри пачки, против папки и против архива —
     ловит перекодированные копии, у которых хеш не совпадает.

Индекс dHash архива кэшируется в local/archive-dhash.json.
"""
import hashlib
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parent.parent
DEST = Path(r"E:\наши изображения\с телефонов и ноутбука")
ROOTS = [Path(r"E:\наши изображения\мои"), Path(r"E:\наши изображения\камера")]
MANIFEST = REPO / "local" / "inbox2-manifest.json"
CACHE = REPO / "local" / "archive-dhash.json"
OUT = REPO / "local" / "inbox2-dedupe.txt"
IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".heic", ".heif", ".webp"}
THRESH = 6


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for block in iter(lambda: f.read(4 << 20), b""):
            h.update(block)
    return h.hexdigest()


def dhash(p: Path, size: int = 8):
    try:
        with Image.open(p) as im:
            im = im.convert("L").resize((size + 1, size), Image.LANCZOS)
        px = list(im.getdata())
        bits = 0
        for row in range(size):
            for col in range(size):
                a = px[row * (size + 1) + col]
                b = px[row * (size + 1) + col + 1]
                bits = (bits << 1) | (1 if a > b else 0)
        return bits
    except Exception:  # noqa: BLE001
        return None


def walk_images(root: Path):
    for dp, _dn, fn in os.walk(root):
        for f in fn:
            p = Path(dp) / f
            if p.suffix.lower() in IMG_EXT and p.is_file():
                yield p


man = json.loads(MANIFEST.read_text(encoding="utf-8"))
items = list(man.values())
lines = [f"новых вложений: {len(items)}", ""]

# --- 1. sha256 ---
by_hash = defaultdict(list)
for it in items:
    p = Path(it["path"])
    if p.exists():
        by_hash[it["sha256"]].append(it)

lines.append("=== ТОЧНЫЕ ДУБЛИ (sha256) ===")
internal = {h: v for h, v in by_hash.items() if len(v) > 1}
lines.append(f"внутри пачки: {sum(len(v) - 1 for v in internal.values())} лишних "
             f"в {len(internal)} группах")
for h, v in internal.items():
    lines.append(f"  {h[:12]} x{len(v)}")
    for it in v:
        lines.append(f"    {it['name']} y={it['year']}")

# против папки назначения
dest_by_hash = {}
for p in DEST.rglob("*"):
    if p.is_file():
        dest_by_hash.setdefault(sha256(p), []).append(p)
hit_dest = [(h, v) for h, v in by_hash.items() if h in dest_by_hash]
lines.append(f"совпало с папкой «с телефонов и ноутбука»: {len(hit_dest)}")
for h, v in hit_dest[:20]:
    lines.append(f"  {h[:12]} {[i['name'] for i in v]} = {[str(x) for x in dest_by_hash[h]]}")

# против архива: предфильтр по размеру
sizes = {it["sha256"]: it["bytes"] for it in items}
arch_by_size = defaultdict(list)
for root in ROOTS:
    for dp, _dn, fn in os.walk(root):
        for f in fn:
            p = Path(dp) / f
            try:
                s = p.stat().st_size
            except OSError:
                continue
            if s in set(sizes.values()):
                arch_by_size[s].append(p)
hit_arch = 0
lines.append(f"кандидатов по размеру в архиве: {sum(len(v) for v in arch_by_size.values())}")
for it in items:
    cands = arch_by_size.get(it["bytes"], [])
    for c in cands:
        if sha256(c) == it["sha256"]:
            hit_arch += 1
            lines.append(f"  СОВПАЛО {it['name']} = {c}")
lines.append(f"точных совпадений с архивом: {hit_arch}")

# --- 2. dHash ---
lines += ["", "=== ПОХОЖИЕ КАРТИНКИ (dHash) ==="]
imgs = [it for it in items if it.get("dhash")]

lines.append("внутри пачки:")
pairs = 0
for i in range(len(imgs)):
    for j in range(i + 1, len(imgs)):
        a, b = imgs[i], imgs[j]
        d = bin(a["dhash"] ^ b["dhash"]).count("1")
        if d <= THRESH:
            pairs += 1
            lines.append(f"  d={d} {a['name']} (y={a['year']}) ~ {b['name']} (y={b['year']})")
lines.append(f"  пар: {pairs}")

# против папки назначения
dest_dh = []
for p in DEST.rglob("*"):
    if p.is_file() and p.suffix.lower() in IMG_EXT:
        dh = dhash(p)
        if dh is not None:
            dest_dh.append((dh, p))
lines.append("против папки «с телефонов и ноутбука»:")
n = 0
for it in imgs:
    for dh, p in dest_dh:
        d = bin(it["dhash"] ^ dh).count("1")
        if d <= THRESH:
            n += 1
            lines.append(f"  d={d} {it['name']} (y={it['year']}) ~ {p}")
lines.append(f"  совпадений: {n}")

# против архива (с кэшем)
cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
arch_dh = []
fresh = 0
for root in ROOTS:
    for p in walk_images(root):
        key = f"{p}|{p.stat().st_size}|{int(p.stat().st_mtime)}"
        if key in cache:
            arch_dh.append((cache[key], p))
            continue
        dh = dhash(p)
        if dh is not None:
            cache[key] = dh
            arch_dh.append((dh, p))
            fresh += 1
            if fresh % 300 == 0:
                CACHE.write_text(json.dumps(cache), encoding="utf-8")
                print(f"… dhash {fresh}")
CACHE.write_text(json.dumps(cache), encoding="utf-8")
lines.append(f"индекс архива: {len(arch_dh)} картинок (досчитано {fresh})")
lines.append("против архива:")
n = 0
for it in imgs:
    for dh, p in arch_dh:
        d = bin(it["dhash"] ^ dh).count("1")
        if d <= THRESH:
            n += 1
            lines.append(f"  d={d} {it['name']} (y={it['year']}) ~ {p}")
lines.append(f"  совпадений: {n}")

OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"ok exact_internal={sum(len(v)-1 for v in internal.values())} "
      f"exact_arch={hit_arch} near_arch={n}")
