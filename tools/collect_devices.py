# -*- coding: utf-8 -*-
"""Сбор фото и видео из канала-архива (посты после объявления) на компьютер.

Скачивает вложения, определяет год (дата в имени -> EXIF -> дата сообщения)
и раскладывает по папкам E:\\наши изображения\\с телефонов и ноутбука\\<год>.
Дубликаты по sha256 пропускает. Манифест — local/devices-manifest.json.

Перед запуском обновить дамп канала: python local/dump_channel.py
"""
import hashlib
import json
import re
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageOps

REPO = Path(__file__).resolve().parent.parent
DUMP = REPO / "local" / "channel-dump.json"
DEST = Path(r"E:\наши изображения\с телефонов и ноутбука")
TMP = REPO / "local" / "devices-tmp"
MANIFEST = REPO / "local" / "devices-manifest.json"
LOG = REPO / "local" / "devices-collect.txt"
MSK = timezone(timedelta(hours=3))

DATE_NAME = re.compile(r"(20\d{2})[._-]?(\d{2})[._-]?(\d{2})[ _-]?(\d{2})?(\d{2})?")
WA_NAME = re.compile(r"IMG-(20\d{2})(\d{2})(\d{2})-WA", re.I)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for block in iter(lambda: f.read(4 << 20), b""):
            h.update(block)
    return h.hexdigest()


def year_from_name(name: str):
    m = WA_NAME.search(name)
    if m:
        return int(m.group(1))
    m = DATE_NAME.search(name)
    if m:
        y = int(m.group(1))
        if 1990 <= y <= 2030:
            return y
    return None


def year_from_exif(p: Path):
    try:
        with Image.open(p) as im:
            ex = im.getexif()
            dt = str(ex.get(36867) or ex.get(306) or "")
        if len(dt) >= 4 and dt[:4].isdigit():
            y = int(dt[:4])
            if 1990 <= y <= 2030:
                return y
    except Exception:  # noqa: BLE001
        return None
    return None


rows = json.loads(DUMP.read_text(encoding="utf-8"))

manifest = {}
if MANIFEST.exists():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
known = {v["sha256"]: k for k, v in manifest.items()}
known_mids = {v["mid"] for v in manifest.values()}

ARCHIVE_TEXT = re.compile(r"^(\d{4} · |\*\*|Сканированные фото)")


def is_archive(r) -> bool:
    return bool(ARCHIVE_TEXT.match((r.get("text") or "").strip()))


# «Входящие» — посты новее объявления. Если объявления уже нет (удалено после
# разбора), берём всё, что не похоже на пост архива и ещё не в манифесте.
idx = next((i for i, r in enumerate(rows)
            if "переместить с других устройств" in (r.get("text") or "").lower()), None)
if idx is not None:
    contrib = rows[:idx + 1]
    lines_head = f"сообщений после объявления: {len(contrib)}"
else:
    contrib = [r for r in rows
               if r.get("atts") and r.get("mid") not in known_mids and not is_archive(r)]
    lines_head = f"сообщений-входящих (без объявления): {len(contrib)}"

DEST.mkdir(parents=True, exist_ok=True)
TMP.mkdir(parents=True, exist_ok=True)
lines = [lines_head]
saved, dupes, errors = 0, 0, 0

for r in contrib:
    ts = datetime.fromtimestamp((r["ts"] or 0) / 1000, tz=MSK)
    for k, a in enumerate(r["atts"]):
        url = a.get("url")
        if not url:
            errors += 1
            lines.append(f"НЕТ URL {r['mid']} {a.get('type')}")
            continue
        base = a.get("filename") or f"{a.get('type')}_{a.get('photo_id') or k}"
        tmp = TMP / re.sub(r'[<>:"/\\|?*]', "_", base)
        for attempt in range(3):
            res = subprocess.run(["curl.exe", "-s", "-L", "-o", str(tmp), url],
                                 capture_output=True, timeout=1800)
            if tmp.exists() and tmp.stat().st_size > 0:
                break
            time.sleep(2 * (attempt + 1))
        if not tmp.exists() or tmp.stat().st_size == 0:
            errors += 1
            lines.append(f"ОШИБКА СКАЧИВАНИЯ {base}")
            continue

        h = sha256(tmp)
        if h in known:
            dupes += 1
            lines.append(f"ДУБЛЬ {base} (уже есть как {known[h]})")
            tmp.unlink()
            continue

        year = year_from_name(base) or year_from_exif(tmp) or ts.year or 2026
        ext = tmp.suffix.lower()
        if a.get("type") == "image" and ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"):
            try:
                with Image.open(tmp) as im:
                    ext = "." + (im.format or "jpg").lower()
            except Exception:  # noqa: BLE001
                ext = ".jpg"
        out_dir = DEST / str(year)
        out_dir.mkdir(parents=True, exist_ok=True)
        name = tmp.name
        if not name.lower().endswith(ext):
            name += ext
        out = out_dir / name
        n = 2
        while out.exists():
            out = out_dir / f"{Path(name).stem}_{n}{ext}"
            n += 1
        tmp.replace(out)
        manifest[str(out)] = {"sha256": h, "mid": r["mid"], "year": year,
                              "name": name, "source": a.get("type"),
                              "bytes": out.stat().st_size}
        known[h] = str(out)
        saved += 1

MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
lines += ["", f"сохранено: {saved}", f"дублей: {dupes}", f"ошибок: {errors}"]
LOG.write_text("\n".join(lines), encoding="utf-8")
print(f"ok saved={saved} dupes={dupes} errors={errors}")
