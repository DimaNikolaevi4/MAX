# -*- coding: utf-8 -*-
"""Случайный фон из пула fallback-заставок (шаг 4 цепочки поставки).

Использование:
  py roles/blogger/tools/pick_fallback.py [--channel na100]

Вывод (ASCII, для подстановки в команды):
  <путь к jpg>
  theme=<dark|light> text=<#hex> panel=<#hex>@<alpha>

Выбирает случайное изображение из
roles/blogger/channels/<slug>/images/fallback/, исключая фон предыдущего
выбора (состояние — local/digest/fallback_state.json, в git не идёт).
Тема печатается как рекомендация; digest_cover_photo.py всё равно
пересчитывает её сам (--theme auto) — здесь она для контроля.
"""
import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

STATE = Path("local/digest/fallback_state.json")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="na100")
    a = ap.parse_args()

    pool = Path(f"roles/blogger/channels/{a.channel}/images/fallback")
    meta_p = pool / "fallback_images.json"
    imgs = sorted(p for p in pool.glob("*.jpg"))
    if not imgs:
        raise SystemExit(f"pool empty: {pool}")
    meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}

    prev = None
    if STATE.exists():
        prev = json.loads(STATE.read_text(encoding="utf-8")).get(a.channel)
    candidates = [p for p in imgs if p.name != prev] or imgs
    pick = random.choice(candidates)

    m = meta.get(pick.name, {})
    theme = m.get("theme", "light")
    sh = (m.get("shading") or {}).get("panel") or {"color": "#071018", "alpha": 0.47}
    print(pick)
    print(f"theme={theme} text={m.get('text_color', '#16305E')} "
          f"panel={sh['color']}@{sh['alpha']}")

    STATE.parent.mkdir(parents=True, exist_ok=True)
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    state[a.channel] = pick.name
    STATE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
