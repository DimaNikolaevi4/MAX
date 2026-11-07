# Парсер брифа и команд для «личного новостного бота».
# Контракт TASK.md: пользователь пишет в личку боту свободный текст;
# опознаём метки формы в любом регистре и в любом месте сообщения:
#   темы: <1-5 тем через запятую>
#   частота: <раз в день | утром+вечером | только будни>
#   источники: <имена сайтов/RSS — опционально>
# Команда стоп распознаётся раньше парсера.
# Кодировка: модуль не печатает кириллицу в консоль (cp1251 на этой машине).
from __future__ import annotations

import re
import unicodedata

FREQUENCY_ALIASES = {
    "раз в день": {"kind": "daily"},
    "в день раз": {"kind": "daily"},
    "утром и вечером": {"kind": "twice"},
    "утром+вечером": {"kind": "twice"},
    "дважды в день": {"kind": "twice"},
    "по вечерам": {"kind": "daily", "hour_hint": "evening"},
    "по утрам": {"kind": "daily", "hour_hint": "morning"},
    "только будни": {"kind": "daily", "weekdays_only": True},
    "будни": {"kind": "daily", "weekdays_only": True},
    "ежедневно": {"kind": "daily"},
}

STOP_WORDS = {"стоп", "стоп.", "стоп!", "стоп,", "хватит", "отписка"}


def _normalize(text: str) -> str:
    # NBSP и похожие юникод-пробелы -> обычный пробел; NFKC для «:» и прочего.
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u00a0", " ").replace("\u202f", " ")
    text = text.replace("‑", "-")
    return text


def _value_after_label(lines: list[str], label: str) -> str | None:
    # Метка может стоять не в начале строки («тест дайджеста, темы: ИИ»),
    # но не внутри слова: перед меткой — начало строки или не-буква.
    pattern = re.compile(
        rf"(?:^|[^\wа-яё]){label}\s*[:\-–—]\s*(.+?)\s*$",
        re.IGNORECASE,
    )
    for line in lines:
        m = pattern.search(_normalize(line))
        if m:
            return m.group(1)
    return None


def _split_list(value: str) -> list[str]:
    parts = re.split(r"[,;/]", value)
    return [p.strip(" .–-") for p in parts if p.strip(" .–-")]


def is_stop(text: str) -> bool:
    normalized = _normalize(text.strip().lower()).strip()
    return normalized in STOP_WORDS or "стоп" == normalized.split(" ")[0] and normalized.split(" ")[0] in STOP_WORDS


def parse_brief(text: str) -> dict:
    """Возвращает:
    ok=True: themes (1..5), frequency (dict), sources (list), warnings (list)
    ok=False: reason — человекочитаемая причина, показываем участнику.
    """
    warnings: list[str] = []
    lines = _normalize(text).split("\n")

    themes_raw = _value_after_label(lines, "темы")
    themes = _split_list(themes_raw) if themes_raw else []
    if not themes:
        return {"ok": False, "reason": "В сообщении нет строки «темы: …» — напишите темы через запятую."}

    if len(themes) > 5:
        themes = themes[:5]
        warnings.append("Тем больше 5 — оставил первые 5, остальные проигнорировал.")

    freq_raw = _value_after_label(lines, "частота")
    frequency = {"kind": "daily"}
    for alias, mapped in FREQUENCY_ALIASES.items():
        if freq_raw and _normalize(freq_raw).lower().startswith(alias) or (
            freq_raw and alias in _normalize(freq_raw).lower()
        ):
            frequency = dict(mapped)
            break
    if freq_raw and frequency == {"kind": "daily"}:
        variants = _split_list(freq_raw)
        lowered = [v.lower() for v in variants]
        if "утром" in lowered and ("вечером" in lowered or "вечер" in lowered):
            frequency = {"kind": "twice"}
        elif "будни" in lowered:
            frequency = {"kind": "daily", "weekdays_only": True}
        elif "вечером" in lowered:
            frequency = {"kind": "daily", "hour_hint": "evening"}
        elif "утром" in lowered:
            frequency = {"kind": "daily", "hour_hint": "morning"}
        else:
            warnings.append(
                f"«частота: {freq_raw}» не распознана — поставил «раз в день». "
                "Варианты: раз в день / утром+вечером / только будни."
            )

    sources_raw = _value_after_label(lines, "источники")
    sources = _split_list(sources_raw) if sources_raw else []

    return {
        "ok": True,
        "themes": themes,
        "frequency": frequency,
        "sources": sources,
        "warnings": warnings,
    }


FORM_HINT = (
    "Скопируйте и допишите:\n"
    "темы: ИИ, нейросети, робототехника\n"
    "частота: раз в день\n"
    "источники: (не обязательно)"
)
