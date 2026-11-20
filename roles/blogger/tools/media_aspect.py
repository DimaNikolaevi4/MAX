# -*- coding: utf-8 -*-
"""Проверка формата одиночного изображения поста (правило AGENTS.md, раздел 5д).

Правило асимметричное (уточнение владельца 20.11.2026):
  • 16:9 или ШИРЕ — допустимо (панораму MAX центр-кропит под карточку);
  • УЖЕ 16:9 — брак: квадрат, портрет, 4:3 занимают узкое окно, и текст поста
    встаёт в узкую колонку.
Нижняя граница — не уже 3:2, то есть соотношение сторон >= 1,50
(это 16:9 с допуском -15 %). Верхней границы нет.

Правило касается только постов с ОДНИМ изображением (текстовые p1/p2); посты-
альбомы (image_files: несколько файлов) под него не попадают.

Использование:
    py roles/blogger/tools/media_aspect.py <файл|папка> [ещё ...] [--min 1.50]
    py roles/blogger/tools/media_aspect.py <файл|папка> --pick

  • без --pick — по каждому изображению печатает размеры, соотношение и вердикт;
    код выхода 1, если хотя бы один кадр уже порога;
  • c --pick — выбирает лучший кадр: среди проходящих — ближайший к 16:9,
    если проходящих нет — самый широкий (утилита, правилом не требуется).

Границы: только измерение и выбор. Ничего не режет и не генерирует — решение
«переделать кадр» остаётся за владельцем (раздел 5д, пункт 4).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

TARGET = 16 / 9          # эталон 1,778
MIN_AR = 3 / 2           # порог: не уже 3:2 (16:9 с допуском -15 %)
EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def measure(path: Path):
    with Image.open(path) as im:
        w, h = im.size
    ar = w / h
    return w, h, ar


def collect(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files.extend(sorted(f for f in p.iterdir() if f.suffix.lower() in EXTS))
        elif p.is_file():
            files.append(p)
        else:
            print(f"нет файла: {p}", file=sys.stderr)
    return files


def verdict(ar: float, min_ar: float) -> str:
    if ar < min_ar:
        return "уже порога — брак"
    if ar >= TARGET:
        return "ok (16:9 или шире)"
    return f"ok, но уже 16:9 (порог {min_ar:.2f})"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Медиа поста: 16:9 или шире (не уже 3:2)")
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("--min", type=float, default=MIN_AR, help="нижний порог соотношения (по умолчанию 1.50)")
    ap.add_argument("--pick", action="store_true", help="выбрать лучший кадр из набора")
    a = ap.parse_args(argv)

    files = collect(a.paths)
    if not files:
        print("нечего проверять", file=sys.stderr)
        return 2

    rows = []
    for f in files:
        w, h, ar = measure(f)
        rows.append({"path": f, "w": w, "h": h, "ar": ar, "ok": ar >= a.min})

    if a.pick:
        passing = [r for r in rows if r["ok"]]
        pool = passing or rows
        best = min(pool, key=lambda r: abs(r["ar"] / TARGET - 1)) if passing else max(
            pool, key=lambda r: r["ar"])
        print(f"{best['path']}\t{best['w']}x{best['h']}\t{best['ar']:.3f}\t"
              f"{'ok' if best['ok'] else 'OUTSIDE'}")
        return 0 if best["ok"] else 1

    bad = 0
    for r in rows:
        if not r["ok"]:
            bad += 1
        print(f"{r['path']}\t{r['w']}x{r['h']}\t{r['ar']:.3f}\t{verdict(r['ar'], a.min)}")
    print(f"\nвсего {len(rows)}, уже порога {a.min:.2f}: {bad}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
