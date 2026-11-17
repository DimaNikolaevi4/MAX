# -*- coding: utf-8 -*-
"""Гейт запрещённых организаций: единая проверка для ВСЕХ путей публикации.

Правило владельца 12.11.2026 (docs/forbidden-orgs.md): любое упоминание
организации из реестров (Минюст — экстремистские, ФСБ — террористические)
запрещено. Весь связанный контекст удаляется, новость заменяется другой.
Дисклеймер «организация запрещена в РФ» не применяется.

Вызывать перед каждой отправкой поста в канал: publish_post.py (MAX, все
каналы), publish_video.py (zabava), publish_telegram.py / tg_direct.py
(Telegram). Паттерны — roles/blogger/config/forbidden_orgs.json.
"""
import json
import re

from .paths import CONFIG

_MESSAGE = (
    "запрещённая организация: упоминание {pat!r} — весь "
    "связанный контекст удаляется, новость заменяется другой "
    "(правило владельца 12.11.2026, docs/forbidden-orgs.md)")


def assert_no_forbidden_orgs(text: str) -> None:
    """Поднять SystemExit, если в тексте упомянута организация из реестров."""
    fob_path = CONFIG / "forbidden_orgs.json"
    if not fob_path.exists():
        raise SystemExit(
            f"не найден {fob_path} — гейт запрещённых организаций не может "
            "отработать, публикация запрещена")
    fob_cfg = json.loads(fob_path.read_text(encoding="utf-8"))
    for p in fob_cfg.get("patterns", []):
        pat = (p.get("pattern", "") if isinstance(p, dict) else str(p)).strip()
        if not pat:
            continue
        # префикс "re:" — сырой regex (для склонений: «в фейсбуке» не ловится
        # через \\bфейсбук\\b, нужна форма «фейсбук\\w*»)
        if pat.startswith("re:"):
            rx = re.compile(pat[3:], re.I)
        else:
            rx = re.compile(rf"\b{re.escape(pat)}\b", re.I)
        if rx.search(text):
            raise SystemExit(_MESSAGE.format(pat=pat))
