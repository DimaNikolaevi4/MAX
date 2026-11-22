# -*- coding: utf-8 -*-
"""Тонкая обёртка над общим движком формата shared/format_core.py.

    py roles/blogger/tools/check_post.py --channel <slug> <post.md> [--core] [--check]

Параметры канала берутся из roles/blogger/config/channels.json; правила —
из AGENTS.md §0 FORMAT CORE v1 и style.md канала. Логики проверки здесь нет.

    --core    принудительно проверить по правилам CORE (даже без format_core: 1);
    --check   только проверка (режим по умолчанию, флаг совместимости);
    --no-spellcheck  пропустить обращение к LanguageTool;
    --report  путь отчёта (по умолчанию local/format-core-check-<slug>.txt).

Новый пост ядра создаётся с полем ``format_core: 1`` во front matter.
Консоль получает только ASCII-сводку; человекочитаемый отчёт — в UTF-8 файл.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from shared import format_core  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Проверка поста единым движком формата")
    ap.add_argument("post", type=Path)
    ap.add_argument("--channel", default="", help="slug канала (иначе — из front matter)")
    ap.add_argument("--core", action="store_true", help="проверить как CORE принудительно")
    ap.add_argument("--check", action="store_true", help="только проверка (по умолчанию)")
    ap.add_argument("--no-spellcheck", action="store_true")
    ap.add_argument("--report", type=Path, default=None)
    args = ap.parse_args(argv)

    result = format_core.check_post(
        args.post,
        channel=args.channel or None,
        force_core=args.core,
        check_spellcheck=not args.no_spellcheck,
    )
    report = args.report or REPO / "local" / f"format-core-check-{result.channel}.txt"
    report = report if report.is_absolute() else REPO / report
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(result.report() + "\n", encoding="utf-8")
    print(format_core.summarize(result))
    print(f"REPORT={report.as_posix()}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
