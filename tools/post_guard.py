"""Сторож публикаций: запрещает отправку в диалоговые и групповые чаты.

Правило (07.11.2026): основная методика публикует только в каналы MAX.
Личный диалог бота AI Now (`@se14808890_bot`, chat_id 537566305) закреплён за
новостным ботом — `experiments/personal-news/`; остальной код туда писать не
должен.

У каналов MAX `chat_id` отрицательный, у диалогов и групп — неотрицательный.
Этого достаточно для дешёвой проверки до сетевых вызовов.
"""
from __future__ import annotations

# Справочно: диалог AI Now. Любой неотрицательный chat_id и так запрещён;
# список оставлен для явного сообщения об ошибке.
BOT_DIALOG_IDS = {537566305}


def assert_channel_chat_id(chat_id: int | str | None, *, tool: str = "publish") -> None:
    """Пропускает только каналы (chat_id < 0). Иначе — отказ.

    Исключение для новостного бота сделано на уровне его собственного кода:
    `experiments/personal-news/` этот модуль не импортирует.
    """
    if chat_id is None or str(chat_id).strip() == "":
        raise SystemExit(f"[{tool}] не задан chat_id.")
    try:
        value = int(chat_id)
    except (TypeError, ValueError):
        raise SystemExit(f"[{tool}] chat_id не число: {chat_id!r}.") from None

    if value >= 0 or value in BOT_DIALOG_IDS:
        raise SystemExit(
            f"[{tool}] Публикация в диалог/группу запрещена (chat_id={value}). "
            "Разрешены только каналы (chat_id < 0). "
            "Личка бота AI Now зарезервирована за experiments/personal-news; "
            "см. docs/bot-publications-archive.md."
        )
