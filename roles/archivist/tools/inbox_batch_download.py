# -*- coding: utf-8 -*-
"""Скачивание новых входящих из канала в промежуточную папку.

Год берётся из подписи-заголовка (подпись идёт перед своей группой); если
подписи нет — 2026. Пишет манифест local/inbox2-manifest.json с sha256 и dHash.
"""
import hashlib
import json
import re
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

import sys  # noqa: E402
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / ".git").exists())))
from shared.paths import REPO  # noqa: E402
ROWS = REPO / "local" / "channel-dump.json"
TMP = REPO / "local" / "inbox2-tmp"
MANIFEST = REPO / "local" / "inbox2-manifest.json"
LOG = REPO / "local" / "inbox2-download.txt"
MARK = "фото от Ани"
MSK = timezone(timedelta(hours=3))
Y = re.compile(r"(?<!\d)(19[5-9]\d|20[0-2]\d)(?!\d)")


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


rows = json.loads(ROWS.read_text(encoding="utf-8"))
idx = next(i for i, r in enumerate(rows) if MARK.lower() in (r["text"] or "").lower())
chrono = rows[:idx][::-1]  # от старого к новому

TMP.mkdir(parents=True, exist_ok=True)
manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
lines = []
year = 2026
saved = skipped = errors = 0

for n, r in enumerate(chrono):
    text = (r["text"] or "").strip()
    m = Y.search(text)
    if m:
        year = int(m.group(1))
        lines.append(f"--- подпись #{n}: {text!r} -> {year}")
        continue
    for k, a in enumerate(r["atts"]):
        key = f"{r['mid']}:{k}"
        if key in manifest and Path(manifest[key]["path"]).exists():
            skipped += 1
            continue
        url = a.get("url")
        if not url:
            errors += 1
            lines.append(f"НЕТ URL {key}")
            continue
        if a["type"] == "image":
            name = f"image_{a.get('photo_id') or k}.webp"
        elif a["type"] == "video":
            name = f"video_{r['mid'][-8:]}_{k}.mp4"
        else:
            name = f"{a['type']}_{r['mid'][-8:]}_{k}"
        dst = TMP / name
        ok = False
        for attempt in range(4):
            subprocess.run(["curl.exe", "-s", "-L", "--max-time", "1800",
                            "-o", str(dst), url], capture_output=True)
            if dst.exists() and dst.stat().st_size > 0:
                ok = True
                break
            time.sleep(2 * (attempt + 1))
        if not ok:
            errors += 1
            lines.append(f"ОШИБКА {key} {a['type']}")
            continue
        h = sha256(dst)
        rec = {"mid": r["mid"], "type": a["type"], "photo_id": a.get("photo_id"),
               "path": str(dst), "name": name, "bytes": dst.stat().st_size,
               "sha256": h, "year": year, "caption": text or "фото от Ани",
               "msg_index": n, "ts": r["ts"]}
        if a["type"] == "image":
            rec["dhash"] = dhash(dst)
            try:
                with Image.open(dst) as im:
                    rec["w"], rec["h"] = im.size
            except Exception:  # noqa: BLE001
                pass
        manifest[key] = rec
        saved += 1
        if saved % 25 == 0:
            MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                encoding="utf-8")
            print(f"… {saved}")

MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
lines += ["", f"скачано: {saved}", f"уже было: {skipped}", f"ошибок: {errors}"]
LOG.write_text("\n".join(lines), encoding="utf-8")
print(f"ok saved={saved} skipped={skipped} errors={errors}")
