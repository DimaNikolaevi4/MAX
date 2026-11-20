# -*- coding: utf-8 -*-
"""Чек-лист выпуска na100 («Пятёрка технологий») — редакционные приёмы.

Методика: docs/na100-editorial-style.md. Инструмент только проверяет и
показывает отчёт; текст не правит (решения принимает редактор).

Использование:
    py roles/blogger/tools/digest_polish.py <пост.md> [--check]

Проверки (пункты 1–9 методики):
  1. хук 40–60 знаков;
  2. пять пунктов, у каждого «Что случилось» и «Почему важно»;
  3. минимум два подзаголовка с цифрой;
  4. длина 3400–3700 (жёсткий предел 4000);
  5. жирные выделения в абзацах — 1–2 на пункт;
  6. длина пункта ≤ 750 знаков;
  7. «Итог дня» есть и не является простым перечислением (эвристика);
  8. вопрос к читателю (не обязателен каждый день);
  9. иллюстрация с атрибуцией («Фото:» / «Иллюстрация:»).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ITEM = re.compile(r"^[1-5]\ufe0f?\u20e3\s+\*\*(.+?)\*\*\s*$", re.M)
SUBHEAD_DIGIT = re.compile(r"\d")


def parse(path: Path) -> tuple[dict, str]:
    raw = path.read_text(encoding="utf-8")
    fm = {}
    body = raw
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].splitlines():
                if ":" in line and not line.startswith(" "):
                    k, v = line.split(":", 1)
                    fm[k.strip()] = v.strip().strip('"')
            body = parts[2]
    return fm, body.strip()


def item_blocks(body: str) -> list[str]:
    """Разбивает тело на блоки пунктов по маркерам 1️⃣…5️⃣."""
    idx = [m.start() for m in re.finditer(r"^[1-5]\ufe0f?\u20e3", body, re.M)]
    if not idx:
        return []
    out = []
    for i, start in enumerate(idx):
        end = idx[i + 1] if i + 1 < len(idx) else len(body)
        out.append(body[start:end])
    return out


def bold_inside(block: str) -> int:
    """Жирные выделения внутри абзацев (исключая подзаголовок пункта)."""
    body = re.sub(r"^[1-5]\ufe0f?\u20e3\s+\*\*.+?\*\*\s*$", "", block, flags=re.M)
    body = body.split("> ")[0]
    return len(re.findall(r"\*\*[^*]+\*\*", body))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Чек-лист выпуска na100")
    ap.add_argument("post", type=Path)
    ap.add_argument("--check", action="store_true", help="только отчёт (по умолчанию тоже)")
    a = ap.parse_args(argv)

    fm, body = parse(a.post)
    problems: list[str] = []
    ok: list[str] = []

    lines = [ln for ln in body.splitlines() if ln.strip()]
    hook = lines[0].strip("* ") if lines else ""
    if 40 <= len(hook) <= 60:
        ok.append(f"хук {len(hook)} знаков (40–60)")
    else:
        problems.append(f"хук {len(hook)} знаков — нужно 40–60: {hook[:70]}")

    items = item_blocks(body)
    subs = ITEM.findall(body)
    if len(items) != 5:
        problems.append(f"пунктов {len(items)}, а должно быть 5")
    else:
        ok.append("5 пунктов")

    what = body.count("Что случилось")
    why = body.count("Почему важно")
    if what != 5 or why != 5:
        problems.append(f"«Что случилось» — {what}, «Почему важно» — {why} (нужно по 5)")
    else:
        ok.append("у каждого пункта есть факт и смысл")

    with_digit = sum(1 for s in subs if SUBHEAD_DIGIT.search(s))
    if with_digit >= 2:
        ok.append(f"цифра в подзаголовке: {with_digit} из 5")
    else:
        problems.append(f"цифра в подзаголовке только у {with_digit} из 5 — нужно ≥2")

    length = len(body)
    if length > 4000:
        problems.append(f"длина {length} — перебор лимита платформы (4000)")
    elif length > 3700:
        problems.append(f"длина {length} — выше бюджета 3700 (выпуски 12/14/17.11 упирались в лимит)")
    elif length < 3400:
        ok.append(f"длина {length} — ниже бюджета (короткий выпуск, допустимо)")
    else:
        ok.append(f"длина {length} — в бюджете 3400–3700")

    for n, block in enumerate(items, 1):
        b = bold_inside(block)
        size = len(block)
        if b > 2:
            problems.append(f"пункт {n}: {b} выделений жирным — больше двух нельзя")
        if size > 750:
            problems.append(f"пункт {n}: {size} знаков — больше 750, резать детали")

    if "Итог дня" not in body:
        problems.append("нет блока «Итог дня»")
    else:
        summary = body.split("Итог дня", 1)[1].split("\n\n")[0][:400]
        commas = summary.count(",") + summary.count(";")
        if commas >= 3 and ("поэтому" not in summary.lower() and "значит" not in summary.lower()
                            and "отсюда" not in summary.lower()):
            problems.append("итог похож на перечисление — нужна причинная связка (приём 5)")
        else:
            ok.append("итог со связкой")

    if "Вопрос к вам" in body:
        ok.append("есть вопрос к читателю (по графику — 2–3 раза в неделю)")
    else:
        ok.append("вопроса нет (допустимо, если не день вопроса)")

    if fm.get("image_file") or fm.get("image"):
        ok.append("иллюстрация прикреплена")
    if "Фото:" in body or "Иллюстрация:" in body:
        ok.append("атрибуция иллюстрации есть")
    else:
        problems.append("нет атрибуции «Фото:» / «Иллюстрация:»")

    print(f"\n=== {a.post.name} ===")
    for o in ok:
        print("  ✅", o)
    for p in problems:
        print("  ⚠️ ", p)
    print(f"\nитог: замечаний {len(problems)}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
