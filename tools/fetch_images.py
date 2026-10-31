# -*- coding: utf-8 -*-
"""Скачивает обложки постов канала AI в локальную библиотеку.

    python tools/fetch_images.py

Читает поле `image:` из channels/ainow/posts/*.md и складывает файлы
в local/images/ainow/<имя поста>.jpg. Библиотека — источник изображений
для постов закрывающихся каналов (na100, administrator, tg_neuro).
"""
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "local" / "images" / "ainow"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for p in sorted((REPO / "channels" / "ainow" / "posts").glob("*.md")):
        raw = p.read_text(encoding="utf-8")
        m = re.search(r"^image:\s*(\S+)$", raw, re.M)
        if not m:
            continue
        dst = OUT / (p.stem + ".jpg")
        if not dst.exists():
            subprocess.run(["curl.exe", "-s", "-L", "-o", str(dst), m.group(1)],
                           capture_output=True)
        t = re.search(r"^\S*\s*\*\*(.+?)\*\*", raw, re.M)
        rows.append(f"{p.stem} | {dst.stat().st_size // 1024} KB | {t.group(1) if t else ''}")
    print("\n".join(rows))
    print(f"всего изображений: {len(rows)}")


if __name__ == "__main__":
    main()
