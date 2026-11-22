# -*- coding: utf-8 -*-
"""Тонкая обёртка чекера выпуска na100 над shared/format_core.py.

    py roles/blogger/tools/digest_polish.py <пост.md> [--check]

Все правила живут в format_core (AGENTS.md §0 + na100/style.md):
заголовок, воздух, CTA адресату, ВОПРОС В КАЖДОМ НОВОМ ВЫПУСКЕ (обязательно),
пять пунктов, «Что случилось»/«Почему важно», цифры в подзаголовках,
бюджет длины, выделения, «Итог дня», атрибуция. Второй копии правил нет.

Новый пост ядра создаётся с полем format_core: 1 во front matter.
Отчёт — в local/digest-polish-<post>.txt (UTF-8), консоль — ASCII-сводка.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from shared import format_core  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="na100 digest check via format_core")
    ap.add_argument("post", type=Path)
    ap.add_argument("--check", action="store_true", help="report only (default)")
    a = ap.parse_args(argv)

    result = format_core.check_post(
        a.post, channel="na100", check_spellcheck=False, extras=True)
    report = REPO / "local" / f"digest-polish-{a.post.stem}.txt"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(result.report() + "\n", encoding="utf-8")
    print(format_core.summarize(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
