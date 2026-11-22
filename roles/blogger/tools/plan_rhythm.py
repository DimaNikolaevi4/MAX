# -*- coding: utf-8 -*-
"""Тонкая обёртка проверки ритма пар catden над shared/format_core.py.

Правило владельца 20.11.2026 (AGENTS.md §5д, catden/style.md):
день 1 — альбом-карусель серии, день 2 — текстовый пост этой же серии.

    py roles/blogger/tools/plan_rhythm.py [--channel catden] [--from DATE] [--to DATE]

Разбор front matter, конфиг канала и сама проверка ритма живут в format_core;
здесь только CLI и печать отчёта. Код 1 — нарушения есть.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from shared import format_core  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="catden series rhythm (format_core)")
    ap.add_argument("--channel", default="catden")
    ap.add_argument("--from", dest="d1", default="")
    ap.add_argument("--to", dest="d2", default="")
    a = ap.parse_args(argv)

    result = format_core.check_series_rhythm(a.channel, a.d1, a.d2)
    lines = [f"channel: {result['channel']}",
             f"pairs: {result['pairs']}, correct: {result['ok']}"]
    if result["bad"]:
        lines.append("VIOLATIONS (post before album):")
        for item in result["bad"]:
            lines.append(f"  {item['series']}: post {item['post']['date']} "
                         f"({item['post']['file']}) <- album {item['album']['date']} "
                         f"({item['album']['file']})")
            if item["extra_albums"]:
                lines.append("    extra albums: " + ", ".join(item["extra_albums"]))
    if result["lonely"]:
        lines.append("SERIES WITHOUT ALBUM:")
        for series, dates in result["lonely"]:
            lines.append(f"  {series}: {', '.join(dates)}")
    lines.append(f"TOTAL violations: {len(result['bad'])}")
    report = REPO / "local" / f"plan-rhythm-{a.channel}.txt"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0 if not result["bad"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
