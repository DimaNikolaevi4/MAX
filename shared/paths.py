# -*- coding: utf-8 -*-
"""Пути репозитория MAX, не зависящие от глубины вложенности скрипта.

Раньше каждый инструмент вычислял корень как ``Path(__file__).parent.parent``.
После разделения на ``roles/<роль>/tools/`` такая схема ломается, поэтому
корень ищется вверх по дереву по маркеру ``.git``.
"""
from __future__ import annotations

from pathlib import Path


def find_repo(start: Path | str | None = None) -> Path:
    """Ближайший родительский каталог с маркером ``.git``."""
    current = Path(start or __file__).resolve()
    for parent in [current, *current.parents]:
        if (parent / ".git").exists():
            return parent
    raise RuntimeError("Не найден корень репозитория MAX (нет .git)")


REPO = find_repo()
LOCAL = REPO / "local"
ROLES = REPO / "roles"
SHARED = REPO / "shared"
ARCHIVE = REPO / "archive"
DOCS = REPO / "docs"


def _resolve(primary: Path, legacy: Path) -> Path:
    """Новое расположение, пока оно не создано — старое (переходный период)."""
    return primary if primary.exists() else legacy


CHANNELS = _resolve(ROLES / "blogger" / "channels", REPO / "channels")
CONFIG = _resolve(ROLES / "blogger" / "config", REPO / "config")


def channel_dir(slug: str) -> Path:
    """Каталог канала блогера: ``roles/blogger/channels/<slug>``."""
    return CHANNELS / slug


def post_dir(slug: str) -> Path:
    """Каталог постов канала."""
    return channel_dir(slug) / "posts"


def tokens_path() -> Path:
    """Файл токенов (gitignored)."""
    return LOCAL / "tokens.json"


def find_post_file(path: str | Path) -> Path:
    """Абсолютный путь к файлу поста (относительные пути — от корня репо)."""
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = REPO / candidate
    return candidate.resolve()
