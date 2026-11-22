# -*- coding: utf-8 -*-
"""Тонкая обёртка канального чекера ainow над shared/format_core.py.

    py roles/blogger/tools/ainow_polish.py <пост.md> [--check]

Проверки §0 FORMAT CORE v1 и дельты ainow/style.md живут только в
format_core: длина, вёрстка, жирные, перелинковка, CTA, вопрос, «выход»
(промпт/чек-лист) и предупреждения об ограничениях. Здесь нет второй копии
правил. Опубликованные посты пропускаются (утверждены владельцем).

Новый пост ядра создаётся с полем format_core: 1 во front matter.
Человекочитаемый отчёт — в local/ainow-polish-<post>.txt (UTF-8), в консоль
только ASCII-сводка.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from shared import format_core  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Ainow post check via format_core")
    ap.add_argument("post", type=Path)
    ap.add_argument("--check", action="store_true", help="report only (default)")
    a = ap.parse_args(argv)

    result = format_core.check_post(
        a.post, channel="ainow", check_spellcheck=False, extras=True)
    report = REPO / "local" / f"ainow-polish-{a.post.stem}.txt"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(result.report() + "\n", encoding="utf-8")
    print(format_core.summarize(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
