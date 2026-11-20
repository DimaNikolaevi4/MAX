# -*- coding: utf-8 -*-
"""Чек-лист публикации ainow (методика: docs/ainow-editorial-style.md).

Только проверка и отчёт; текст не правит.

    py roles/blogger/tools/ainow_polish.py <пост.md> [--check]

Проверки:
  1. длина ≤ 4000 (комфорт ≤ 3600);
  2. нет литеральных списков (`* `, `- `, `1. `), таблиц `|` и `###`;
  3. жирных выделений внутри абзацев ≤ 6 (подзаголовки не считаются);
  4. перелинковка: 1–2 ссылки на прошлые посты канала;
  5. вопрос в конце (перед CTA);
  6. CTA-цитата со ссылкой на канал;
  7. картинка в front matter;
  8. «выход»: промпт / чек-лист / шаги;
  9. предупреждения об ограничениях (⚠ / лимит / не работает).
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path


def parse(path: Path) -> tuple[dict, str]:
    raw = path.read_text(encoding="utf-8")
    fm, body = {}, raw
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].splitlines():
                if ":" in line and not line.startswith(" "):
                    k, v = line.split(":", 1)
                    fm[k.strip()] = v.strip().strip('"')
            body = parts[2]
    return fm, body.strip()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Чек-лист поста ainow")
    ap.add_argument("post", type=Path)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)

    fm, body = parse(a.post)
    ok, bad = [], []

    length = len(body)
    if length > 4000:
        bad.append(f"длина {length} — перебор лимита API 4000")
    elif length > 3600:
        bad.append(f"длина {length} — выше комфортного 3600 (лимит 4000)")
    else:
        ok.append(f"длина {length}")

    patterns = {
        "литеральные `* `": r"^\* ",
        "литеральные `- `": r"^- ",
        "литеральные `1. `": r"^\d\. ",
        "таблицы `|`": r"^\|",
        "заголовки `###`": r"^#{1,6} ",
    }
    found = {name: len(re.findall(rx, body, re.M)) for name, rx in patterns.items()}
    for name, cnt in found.items():
        if cnt:
            bad.append(f"{name}: {cnt} — в MAX не рендерится, заменить на «— »/1️⃣/жирную строку")
    if not any(found.values()):
        ok.append("вёрстка чистая (без литеральных списков и ###)")

    inline_bold = 0
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("**") and s.endswith("**") and s.count("**") == 2:
            continue  # подзаголовок
        inline_bold += len(re.findall(r"\*\*[^*]+\*\*", line))
    if inline_bold > 6:
        bad.append(f"жирных выделений в абзацах: {inline_bold} — бюджет ≤6")
    else:
        ok.append(f"жирных выделений в абзацах: {inline_bold}")

    links = re.findall(r"https://max\.ru/channel_ainow/[A-Za-z0-9_-]+", body)
    if not links:
        bad.append("нет перелинковки: нужна 1–2 ссылки на прошлые посты (правило 7)")
    elif len(links) > 2:
        bad.append(f"перелинковки {len(links)} — больше двух нельзя")
    else:
        ok.append(f"перелинковка: {len(links)}")

    tail = body.split("> **Подписывайтесь")[0].strip()
    if "?" in tail[-400:]:
        ok.append("вопрос в конце есть")
    else:
        bad.append("нет вопроса к читателю в конце (правило тона)")

    if "> **Подписывайтесь" in body and "https://max.ru/channel_ainow" in body:
        ok.append("CTA-цитата со ссылкой на канал")
    else:
        bad.append("нет CTA-цитаты со ссылкой на канал")

    if fm.get("image_file") or fm.get("image"):
        ok.append("картинка в front matter")
    else:
        bad.append("нет картинки в front matter")

    if re.search(r"промпт|чек-лист|шаг\s*1|1️⃣", body, re.I) or "`" in body:
        ok.append("есть «выход» (промпт / чек-лист / шаги)")
    else:
        bad.append("нет «выхода»: промпта, чек-листа или порядка шагов")

    is_review = bool(re.search(r"бесплатн|сервис|инструмент|платформ", body, re.I))
    if re.search(r"⚠|лимит|не работает|блокир|ограничен", body, re.I):
        ok.append("предупреждения об ограничениях есть")
    elif is_review:
        bad.append("похоже на обзор инструментов, но нет предупреждений (⚠/лимит)")
    else:
        ok.append("предупреждения не требуются (не обзор инструментов)")

    print(f"\n=== {a.post.name} ===")
    for o in ok:
        print("  ✅", o)
    for b in bad:
        print("  ⚠️ ", b)
    print(f"\nитог: замечаний {len(bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
