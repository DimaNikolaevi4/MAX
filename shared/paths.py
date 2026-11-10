# -*- coding: utf-8 -*-
"""Пути репозитория MAX, не зависящие от глубины вложенности скрипта.

Раньше каждый инструмент вычислял корень как ``Path(__file__).parent.parent``.
После разделения на ``roles/<роль>/tools/`` такая схема ломается, поэтому
корень ищется вверх по дереву по маркеру ``.git``.
"""
from __future__ import annotations

import json
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


def channels_config() -> dict:
    """Реестр каналов `roles/blogger/config/channels.json`."""
    return json.loads((CONFIG / "channels.json").read_text(encoding="utf-8"))


def ensure_publish_allowed(slug: str, tool: str = "публикатор") -> None:
    """Запрет публикации в канал со `status: to_delete` (канал закрыт, ждёт удаления)."""
    for record in channels_config().get("channels", []):
        if record.get("slug") == slug and record.get("status") == "to_delete":
            raise SystemExit(
                f"{tool}: канал {slug!r} под удаление "
                f"({record.get('delete_on', 'дата не указана')}) — публикация запрещена"
            )


def find_post_file(path: str | Path) -> Path:
    """Абсолютный путь к файлу поста (относительные пути — от корня репо)."""
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = REPO / candidate
    return candidate.resolve()
