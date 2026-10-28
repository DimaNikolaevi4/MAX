# -*- coding: utf-8 -*-
"""Сборка Markdown поста точными заменами (с проверкой числа вхождений).

Использование:
    python tools/build_markdown.py <пост.md> <replacements.json> <out.md> [--payload out.json]

replacements.json — массив объектов:
    [ {"old": "текст как в файле", "new": "**текст**", "expect": 1}, ... ]

Каждая замена проверяется: если «old» встречается не «expect» раз — сборка
падает, ничего не записывается. Так ловятся неразрывные пробелы (\xa0) и
другие невидимые символы до отправки в API.
"""
import json
import sys
from pathlib import Path


def main() -> None:
    argv = sys.argv[1:]
    payload_path = None
    if "--payload" in argv:
        i = argv.index("--payload")
        payload_path = argv[i + 1]
        del argv[i:i + 2]
    if len(argv) != 3:
        raise SystemExit(
            "Использование: python tools/build_markdown.py <пост.md> <replacements.json> <out.md> [--payload out.json]")

    post_path, repl_path, out_path = argv
    raw = Path(post_path).read_text(encoding="utf-8")

    # отрезаем front matter
    import re
    m = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n?", raw, re.S)
    text = raw[m.end():] if m else raw
    text = text.strip() + "\n"

    repls = json.loads(Path(repl_path).read_text(encoding="utf-8"))
    log = []
    for r in repls:
        old, new = r["old"], r["new"]
        expect = int(r.get("expect", 1))
        n = text.count(old)
        if n != expect:
            raise SystemExit(f"ОШИБКА: {old[:60]!r} встречается {n} раз(а), ожидалось {expect}")
        text = text.replace(old, new)
        log.append(f"OK ({n}): {old[:60]!r}")

    Path(out_path).write_text(text, encoding="utf-8")
    log.append(f"Длина: {len(text)} символов (лимит 4000)")
    Path(out_path).with_suffix(".log").write_text("\n".join(log), encoding="utf-8")

    if payload_path:
        Path(payload_path).write_text(
            json.dumps({"text": text, "format": "markdown"}, ensure_ascii=False),
            encoding="utf-8")
    print(f"ok -> {out_path}")


if __name__ == "__main__":
    main()
