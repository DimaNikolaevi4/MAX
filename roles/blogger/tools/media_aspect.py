# -*- coding: utf-8 -*-
"""Проверка формата медиа поста (правило AGENTS.md, раздел 5д).

Целевое соотношение — 16:9 (эталон 1920x1080 / 1980x1114), допуск ±15 %.

Использование:
    py roles/blogger/tools/media_aspect.py <файл|папка> [ещё ...] [--tol 0.15]
    py roles/blogger/tools/media_aspect.py <файл|папка> --pick

Что делает:
  • без --pick — по каждому изображению печатает размеры, соотношение сторон
    и вердикт «ok» / «outside»; код выхода 1, если хотя бы один кадр вне допуска;
  • c --pick — из переданного набора выбирает кадр, ближайший к 16:9
    (для каналов с альбомами: заголовок поста ставится из ближайшего кадра).

Границы: только измерение и выбор, ничего не режет и не генерирует —
решение «переделать кадр» остаётся за владельцем (раздел 5д, пункт 3).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

TARGET = 16 / 9
EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def measure(path: Path):
    with Image.open(path) as im:
        w, h = im.size
    ar = w / h
    return w, h, ar, ar / TARGET


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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Проверка медиа поста на 16:9")
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("--tol", type=float, default=0.15, help="допуск, доля (по умолчанию 0,15)")
    ap.add_argument("--pick", action="store_true", help="выбрать ближайший к 16:9 кадр")
    a = ap.parse_args(argv)

    files = collect(a.paths)
    if not files:
        print("нечего проверять", file=sys.stderr)
        return 2

    rows = []
    for f in files:
        w, h, ar, rel = measure(f)
        ok = abs(rel - 1) <= a.tol
        rows.append({"path": f, "w": w, "h": h, "ar": ar, "rel": rel, "ok": ok})

    if a.pick:
        best = min(rows, key=lambda r: abs(r["rel"] - 1))
        mark = "ok" if best["ok"] else "OUTSIDE"
        print(f"{best['path']}\t{best['w']}x{best['h']}\t{best['ar']:.3f}\t{mark}")
        return 0 if best["ok"] else 1

    bad = 0
    for r in rows:
        mark = "ok" if r["ok"] else "outside"
        if not r["ok"]:
            bad += 1
        print(f"{r['path']}\t{r['w']}x{r['h']}\t{r['ar']:.3f}\t{r['rel']:.2f}x of 16:9\t{mark}")
    print(f"\nвсего {len(rows)}, вне допуска ±{a.tol:.0%}: {bad}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
