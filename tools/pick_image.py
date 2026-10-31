# -*- coding: utf-8 -*-
"""Выбирает изображение из архива AI для поста закрывающегося канала.

    python tools/pick_image.py --channel na100
    python tools/pick_image.py --channel administrator --topic дашборд
    python tools/pick_image.py --channel tg_neuro --show     # только посмотреть

Правило проекта: карточки для na100 / administrator / tg_neuro не рисуются,
изображение берётся из архива основного канала AI (local/images/ainow).
Скрипт выбирает картинку, которая дольше всех не использовалась в этом канале,
и запоминает выбор в local/images/used.json.
"""
import argparse
import json
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
POOL = REPO / "local" / "images" / "ainow"
USED = REPO / "local" / "images" / "used.json"


def load_used() -> dict:
    if USED.exists():
        return json.loads(USED.read_text(encoding="utf-8"))
    return {}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", required=True, choices=["na100", "administrator", "tg_neuro"])
    ap.add_argument("--topic", default=None, help="подстрока в имени файла (пост AI-источника)")
    ap.add_argument("--show", action="store_true", help="не записывать выбор")
    a = ap.parse_args()

    files = sorted(POOL.glob("*.jpg"))
    if not files:
        raise SystemExit("библиотека пуста: сначала python tools/fetch_images.py")
    if a.topic:
        filtered = [f for f in files if a.topic.lower() in f.stem.lower()]
        files = filtered or files

    used = load_used()
    ch_used = used.get(a.channel, {})

    def rank(f: Path):
        return (ch_used.get(f.stem, ""), f.stem)

    pick = sorted(files, key=rank)[0]
    rel = pick.relative_to(REPO).as_posix()
    if not a.show:
        ch_used[pick.stem] = date.today().isoformat()
        used[a.channel] = ch_used
        USED.parent.mkdir(parents=True, exist_ok=True)
        USED.write_text(json.dumps(used, ensure_ascii=False, indent=2), encoding="utf-8")
    print(rel)


if __name__ == "__main__":
    main()
