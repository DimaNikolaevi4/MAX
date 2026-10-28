# -*- coding: utf-8 -*-
"""Снятие фрагментов разметки из сохранённого ответа GET /messages.

Позиции разметки MAX хранит в UTF-16 кодовых единицах (эмодзи вне BMP = 2
единицы), поэтому перед срезом позиции пересчитываются в кодовые точки.

Использование:
    python tools/markup_fragments.py <message.json> <out.txt>

где message.json — ответ GET /messages/{mid} (или body сообщения).
"""
import json
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("Использование: python tools/markup_fragments.py <message.json> <out.txt>")
    d = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    body = d.get("body", d)
    text = body["text"]
    markup = body.get("markup") or []

    prefix = [0]
    for ch in text:
        prefix.append(prefix[-1] + (2 if ord(ch) > 0xFFFF else 1))

    def cp(u16: int) -> int:
        lo, hi = 0, len(prefix) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if prefix[mid] <= u16:
                lo = mid
            else:
                hi = mid - 1
        return lo

    lines = [
        f"длина текста: {len(text)}",
        f"вложений: {len(body.get('attachments') or [])}",
        f"элементов разметки: {len(markup)}",
        "",
    ]
    for m in markup:
        s, e = cp(m["from"]), cp(m["from"] + m["length"])
        seg = text[s:e]
        url = f" url={m['url']}" if m.get("url") else ""
        lines.append(f"{m['type']:>13} {s:>5}-{e:<5} = {seg!r}{url}")

    Path(sys.argv[2]).write_text("\n".join(lines), encoding="utf-8")
    print(f"ok -> {sys.argv[2]}")


if __name__ == "__main__":
    main()
