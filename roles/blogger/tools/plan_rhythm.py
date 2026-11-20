# -*- coding: utf-8 -*-
"""Проверка ритма пар: альбом серии должен выходить ДО её текстового поста.

Правило владельца 20.11.2026 (AGENTS.md, раздел 5д + catden/style.md):
  день 1 — альбом-карусель серии, день 2 — текстовый пост этой же серии.

Использование:
    py roles/blogger/tools/plan_rhythm.py [--channel catden] [--from 2026-11-20] [--to 2027-01-18]

Печатает: серии, где пост стоит раньше альбома (нарушение), серии без пары,
и сводку. Код выхода 1, если нарушения есть.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def front_matter(raw: str) -> dict:
    m = re.match(r"\A---\r?\n(.*?)\r?\n---", raw, re.S)
    fm = {}
    if not m:
        return fm
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip().strip('"')
    return fm


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Ритм пар catden: альбом → пост")
    ap.add_argument("--channel", default="catden")
    ap.add_argument("--from", dest="d1", default="")
    ap.add_argument("--to", dest="d2", default="")
    a = ap.parse_args(argv)

    base = REPO / "roles" / "blogger" / "channels" / a.channel / "posts"
    series: dict[str, list] = {}
    for p in sorted(base.glob("*.md")):
        date = p.name[:10]
        if a.d1 and date < a.d1:
            continue
        if a.d2 and date > a.d2:
            continue
        fm = front_matter(p.read_text(encoding="utf-8"))
        ser = fm.get("series") or p.stem.split("-")[3]
        files = fm.get("image_files") or fm.get("image_file") or ""
        names = [x.strip() for x in files.split("|") if x.strip()]
        album = bool(fm.get("image_files")) or bool(re.search(r"-img\d+$", p.stem))
        series.setdefault(ser, []).append({"date": date, "file": p.name, "album": album,
                                           "images": len(names),
                                           "status": fm.get("status", "")})

    bad, lonely, ok = [], [], 0
    for ser, posts in sorted(series.items()):
        albums = sorted([x for x in posts if x["album"]], key=lambda x: x["date"])
        texts = sorted([x for x in posts if not x["album"]], key=lambda x: x["date"])
        if not albums:
            lonely.append((ser, [t["date"] for t in texts]))
            continue
        if not texts:
            continue
        first_album, first_text = albums[0]["date"], texts[0]["date"]
        if first_album < first_text:
            ok += 1
        else:
            bad.append({
                "series": ser,
                "album": albums[0],
                "post": texts[0],
                "extra_albums": [x["date"] for x in albums[1:]],
            })

    print(f"канал: {a.channel}; серий с парой: {ok + len(bad)}; в правильном порядке: {ok}")
    if bad:
        print("\nНАРУШЕНИЕ (пост раньше альбома):")
        for b in bad:
            print(f"  серия {b['series']}: пост {b['post']['date']} ({b['post']['file']}) "
                  f"← альбом {b['album']['date']} ({b['album']['file']})")
            if b["extra_albums"]:
                print(f"    доп. альбомы: {', '.join(b['extra_albums'])}")
    if lonely:
        print("\nсерии без альбома (только текстовые посты):")
        for ser, dates in lonely:
            print(f"  серия {ser}: {', '.join(dates)}")
    print(f"\nитог: нарушений {len(bad)}")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
