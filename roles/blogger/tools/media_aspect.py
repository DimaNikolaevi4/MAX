# -*- coding: utf-8 -*-
"""Тонкая обёртка над общим движком пропорций shared/format_core.py.

Правило AGENTS.md §0.3 / §5д: одиночное изображение ИЛИ видео —
соотношение сторон >= media_aspect_min из channels.json (по умолчанию 1.50),
верхней границы нет. Альбомы от 2 файлов под правило не попадают;
media_aspect_exempt: true во front matter разрешает исключение.

    py roles/blogger/tools/media_aspect.py <файл|папка> [ещё ...] [--min 1.50]
    py roles/blogger/tools/media_aspect.py <файл|папка> --pick
    py roles/blogger/tools/media_aspect.py <файл> --channel catden

Измерение (PIL для картинок, ffprobe для видео), порог и вердикт живут
только в format_core; здесь нет второй копии правил. Код 1 — нарушение.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from shared import format_core  # noqa: E402

MIN_AR = format_core.DEFAULT_MEDIA_MIN
TARGET = 16 / 9
EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp",
        ".mp4", ".mov", ".mkv", ".webm"}


def measure(path: Path):
    """Обратная совместимость: (w, h, aspect) или None."""
    return format_core.measure_media(path)


def collect(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files.extend(sorted(f for f in p.iterdir() if f.suffix.lower() in EXTS))
        elif p.is_file():
            files.append(p)
        else:
            print(f"NO_FILE {p}", file=sys.stderr)
    return files


def verdict(ar: float, min_ar: float) -> str:
    if ar < min_ar:
        return "FAIL aspect below minimum"
    if ar >= TARGET:
        return "OK 16:9 or wider"
    return f"OK but narrower than 16:9 (min {min_ar:.2f})"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Media aspect check (format_core)")
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("--min", type=float, default=None,
                    help="lower aspect bound (default: media_aspect_min from config)")
    ap.add_argument("--channel", default="", help="channel slug to read media_aspect_min")
    ap.add_argument("--pick", action="store_true", help="pick the best frame")
    a = ap.parse_args(argv)

    min_ar = a.min
    if min_ar is None:
        if a.channel:
            try:
                min_ar = format_core.float_param(
                    format_core.channel_config(a.channel),
                    "media_aspect_min", format_core.DEFAULT_MEDIA_MIN)
            except KeyError:
                min_ar = format_core.DEFAULT_MEDIA_MIN
        else:
            min_ar = format_core.DEFAULT_MEDIA_MIN

    files = collect(a.paths)
    if not files:
        print("NOTHING_TO_CHECK", file=sys.stderr)
        return 2

    rows = []
    for f in files:
        measured = measure(f)
        if measured is None:
            print(f"{f}\tUNMEASURABLE")
            continue
        w, h, ar = measured
        rows.append({"path": f, "w": w, "h": h, "ar": ar, "ok": ar >= min_ar})

    if a.pick:
        passing = [r for r in rows if r["ok"]] or rows
        best = (min(passing, key=lambda r: abs(r["ar"] / TARGET - 1)) if any(
            r["ok"] for r in rows) else max(passing, key=lambda r: r["ar"]))
        print(f"{best['path']}\t{best['w']}x{best['h']}\t{best['ar']:.3f}\t"
              f"{'OK' if best['ok'] else 'OUTSIDE'}")
        return 0 if best["ok"] else 1

    bad = 0
    for r in rows:
        if not r["ok"]:
            bad += 1
        print(f"{r['path']}\t{r['w']}x{r['h']}\t{r['ar']:.3f}\t{verdict(r['ar'], min_ar)}")
    print(f"TOTAL {len(rows)}, BELOW {min_ar:.2f}: {bad}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
