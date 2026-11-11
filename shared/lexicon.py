# -*- coding: utf-8 -*-
"""Сканер штампов и канцелярита humanizer-ru (обёртка, только WARN).

Введено 11.11.2026 (третий слой проверки читаемости na100). Проект:
https://github.com/ilyautov/humanizer-ru (MIT), PyPI-пакет `ru-humanizer`.
Детектор без автоправки: балл чистоты, жёсткие запреты, маркеры с
позициями, номинальность (сущ./глаг. — прокси канцелярита). Запуск
локальный, текст с машины не уходит.

Пакет опционален: если `ru-humanizer` не установлен, возвращается
status="unavailable" и публикатор продолжает (как с LanguageTool).
Проверено на версии 3.32.0: при обновлении пакета поведение WARN может
тихо измениться — при апгрейде прогонять на эталонных текстах
(выпуск №2 na100 + тест «Отмечается, что внедрение решения…» из отчёта
11.11.2026).

Категории маркеров, легальные для канала (наш формат из style.md —
нумерация 1️⃣–5️⃣, жирные подзаголовки), передаются в ignore_categories:
роли канала — `channels/<slug>/lexicon-ignore.json` (поле categories).

CLI:
  python shared/lexicon.py <файл-с-текстом.txt> [--genre news]
"""
import argparse
import json
import re
import shutil
import subprocess
import sys


def _find_scanner() -> str:
    exe = shutil.which("ru-humanizer")
    if exe:
        return exe
    # PyPI ставит exe в Scripts рядом с python
    from pathlib import Path
    cand = Path(sys.executable).parent / "Scripts" / "ru-humanizer.exe"
    if cand.exists():
        return str(cand)
    return ""


def _line_of(text: str, offset: int) -> int:
    return text[:offset].count("\n") + 1


def check_lexicon(text: str, genre: str = "news",
                  ignore_categories=()) -> dict:
    """Вернуть {status, items, score, message}.

    items — готовые строки-замечания; status: ok | unavailable.
    """
    text = (text or "").strip()
    if not text:
        return {"status": "ok", "items": [], "score": None, "message": "пустой текст"}
    exe = _find_scanner()
    if not exe:
        return {"status": "unavailable", "items": [], "score": None,
                "message": "пакет ru-humanizer не найден (py -m pip install ru-humanizer)"}
    try:
        r = subprocess.run(
            [exe, "-", "--genre", genre, "--json"],
            input=text.encode("utf-8"), capture_output=True, timeout=120)
        data = json.loads(r.stdout.decode("utf-8", "replace"))
    except FileNotFoundError:
        return {"status": "unavailable", "items": [], "score": None,
                "message": "пакет ru-humanizer не найден (py -m pip install ru-humanizer)"}
    except Exception as e:  # noqa: BLE001
        return {"status": "unavailable", "items": [], "score": None,
                "message": f"сканер ru-humanizer упал: {e!r}"[:160]}

    ignore = {str(c).strip().lower() for c in ignore_categories if str(c).strip()}
    ignored = {"hard_bans": 0, "markers": 0, "penalties": 0}

    def is_ignored(category: str) -> bool:
        c = (category or "").strip().lower()
        return any(w in c for w in ignore)

    items = []
    for b in (data.get("hard_bans") or []):
        cat = b.get("category", "") if isinstance(b, dict) else ""
        if is_ignored(cat):
            ignored["hard_bans"] += 1
            continue
        frag = (b.get("text") or b.get("name") or json.dumps(b, ensure_ascii=False))[:60]
        line = _line_of(text, int(b.get("positions", [0])[0])) if b.get("positions") else "?"
        items.append(f"жёсткий запрет «{frag}» (строка {line})")
    for m in (data.get("markers") or []):
        cat = m.get("category", "")
        if is_ignored(cat):
            ignored["markers"] += 1
            continue
        pos = ", ".join(str(_line_of(text, p)) for p in (m.get("positions") or [])[:3])
        items.append(f"[{cat}] «{m.get('name')}» ×{m.get('count', '?')} (стр. {pos})")
    for p in (data.get("penalties") or []):
        reason = p.get("reason", "")
        if is_ignored(reason):
            ignored["penalties"] += 1
            continue
        items.append(f"{reason} ({p.get('points', '?')} к баллу)")

    return {
        "status": "ok",
        "items": items,
        "score": data.get("score"),
        "message": f"чистота {data.get('score')}/100"
                   + (f", скрыто легальных: {sum(ignored.values())}" if ignored else ""),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="файл с текстом")
    ap.add_argument("--genre", default="news",
                    choices=["marketing", "academic", "legal", "fiction", "news"])
    ap.add_argument("--ignore", default="",
                    help="легальные категории через запятую")
    a = ap.parse_args()
    text = open(a.source, encoding="utf-8").read()
    r = check_lexicon(text, genre=a.genre,
                      ignore_categories=[x for x in a.ignore.split(",") if x.strip()])
    if r["status"] == "unavailable":
        print("СКАНЕР НЕДОСТУПЕН: " + r["message"])
        raise SystemExit(2)
    for item in r["items"]:
        print("WARN: " + item)
    print(r["message"])
    raise SystemExit(0)


if __name__ == "__main__":
    main()
