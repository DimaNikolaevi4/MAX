# -*- coding: utf-8 -*-
"""Единый движок проверки формата постов MAX (FORMAT CORE v1, AGENTS.md §0).

Источник истины по приоритету:
    AGENTS.md §0 -> AGENTS.md -> style.md канала -> docs/ -> README.md.

Параметры каналов (лимиты, CTA, interlink, profile) берутся ТОЛЬКО из
``roles/blogger/config/channels.json``; фразы реакций — из
``roles/blogger/config/reactions-registry.json`` и
``roles/blogger/channels/zabava/reactions-phrases.json``.

Режимы:
    CORE   — во front matter есть ``format_core: 1`` (или выставлен --core);
    LEGACY — поля нет: проверяется только критический минимум (длина, статус,
             наличие CTA, пропорции одиночного медиа, запрещённые организации,
             орфография). Старые посты без финального вопроса проходят.

Профили:
    core     — ainow, na100, catden, administrator;
    zabava   — канонический короткий формат style.md;
    telegram — канонический формат tg_neuro/style.md.

Модуль не публикует и не отправляет ничего в сеть, кроме необязательной
проверки орфографии через shared.text_check (как и остальные чекеры).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable

try:  # импорт как пакет (обычный путь из инструментов)
    from .paths import (CHANNELS, CONFIG, REPO, channel_dir, channels_config,  # noqa: E402
                        ensure_publish_allowed, post_dir)
except ImportError:  # прямой запуск: py shared/format_core.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from shared.paths import (CHANNELS, CONFIG, REPO, channel_dir, channels_config,  # noqa: E402
                              ensure_publish_allowed, post_dir)

MSK = timezone(timedelta(hours=3))
REACTIONS_REGISTRY = CONFIG / "reactions-registry.json"
CTA_MISSING_WARNING = (
    "cta_target не указан, установлено 'self'. Проверьте чередование.")

DEFAULT_HEADLINE_MAX = 60
DEFAULT_BOLD_BUDGET = 6
DEFAULT_LENGTH_HARD = 4000
DEFAULT_LENGTH_SOFT = 3600
DEFAULT_MEDIA_MIN = 1.5
DEFAULT_BODY_MAX = 200
DEFAULT_BODY_LINES = 2
TELEGRAM_CAPTION_MAX = 1000

CTA_CORE_RE = re.compile(
    r"^>\s*\*\*Подписывайтесь на \[([^\]]+)\]\(([^)\s]+)\)\*\*\s*—\s*(.+)$")
CTA_ZABAVA_RE = re.compile(
    r"^Подпишись на канал\s+\*\*\[([^\]]+)\]\(([^)\s]+)\)\*\*\s*—\s*(.+)$")
CTA_TELEGRAM_RE = re.compile(
    r"^\*\*Подписывайтесь на\s+\[?([^\]]+?)\]?\(([^)\s]+)\)\*\*\s*—\s*(.+)$|"
    r"^Подписывайтесь на\s+\*\*\[([^\]]+)\]\(([^)\s]+)\)\*\*\s*—\s*(.+)$")
LINK_RE = re.compile(r"\[[^\]]+\]\((https?://[^)\s]+)\)")
POST_LINK_RE = re.compile(r"(?:max\.ru/channel_[A-Za-z0-9_-]+|t\.me/[^/\s]+)/[A-Za-z0-9_-]+")
REACTION_RE = re.compile(r"реакц|🔥|поставьте|ставьте|жмите|лайк|реакцию", re.I)
EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D]")
# Маркеры перечислений, разрешённые вместо markdown-списков (§0.9).
ALLOWED_MARKERS = ("— ", "• ", "1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣")


# ---------------------------------------------------------------------------
# Front matter: разбор и запись с сохранением неизвестных полей и комментариев
# ---------------------------------------------------------------------------

def _split_comment(value: str) -> tuple[str, str]:
    """Отделяет встроенный комментарий от значения front matter."""
    if value[:1] in ('"', "'"):
        quote = value[0]
        i = 1
        while i < len(value):
            if value[i] == "\\":
                i += 2
                continue
            if value[i] == quote:
                return value[:i + 1], value[i + 1:]
            i += 1
        return value, ""
    m = re.search(r"\s+#", value)
    if m:
        return value[:m.start()], value[m.start():]
    return value, ""


def _format_value(value, old: str = "") -> str:
    """Сериализует значение, сохраняя стиль кавычек уже существующего поля."""
    text = str(value)
    old_value, _ = _split_comment(old)
    if old_value[:1] in ('"', "'"):
        quote = old_value[0]
        esc = text.replace("\\", "\\\\").replace(quote, "\\" + quote)
        return f"{quote}{esc}{quote}"
    if (not text) or text != text.strip() or "\n" in text or re.search(r"\s#", text):
        return json.dumps(text, ensure_ascii=False)
    return text


@dataclass
class FrontMatter:
    """Line-based front matter: порядок полей и комментарии сохраняются.

    Известные движку поля меняются на месте; неизвестные (format_core,
    cta_target, reactions, approved_by_owner, spell_ignore, media_note,
    media_aspect_exempt, publish_time и любые другие) остаются как есть.
    """

    lines: list[str] = field(default_factory=list)
    values: dict[str, str] = field(default_factory=dict)
    positions: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, values: dict) -> "FrontMatter":
        obj = cls()
        for key, value in (values or {}).items():
            if re.fullmatch(r"[\w.-]+", str(key)):
                obj.lines.append(f"{key}: {_format_value(value)}")
                obj.positions[str(key)] = len(obj.lines) - 1
                obj.values[str(key)] = str(value)
        return obj

    @classmethod
    def parse(cls, raw: str) -> "FrontMatter":
        m = re.match(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", raw, re.S)
        obj = cls()
        if not m:
            return obj
        obj.lines = m.group(1).splitlines()
        for i, line in enumerate(obj.lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip()
            if not re.fullmatch(r"[\w.-]+", key):
                continue
            value, _ = _split_comment(value.strip())
            obj.values[key] = value.strip().strip('"').strip("'")
            obj.positions[key] = i
        return obj

    def get(self, key: str, default: str | None = None) -> str | None:
        return self.values.get(key, default)

    def set(self, key: str, value) -> None:
        text = _format_value(value, self.lines[self.positions[key]]
                             if key in self.positions else "")
        if key in self.positions:
            line = self.lines[self.positions[key]]
            m = re.match(r"^(\s*)([\w.-]+)(\s*:\s*)(.*)$", line)
            if m:
                _, raw_value = _split_comment(m.group(4))
                comment = m.group(4)[len(raw_value):]
                self.lines[self.positions[key]] = (
                    f"{m.group(1)}{m.group(2)}{m.group(3)}{text}{comment}")
            else:
                self.lines[self.positions[key]] = f"{key}: {text}"
        else:
            self.lines.append(f"{key}: {text}")
            self.positions[key] = len(self.lines) - 1
        self.values[key] = str(value)

    def update(self, values: dict) -> None:
        for key, value in values.items():
            self.set(key, value)

    def pop(self, key: str, default: str | None = None) -> str | None:
        value = self.values.pop(key, default)
        if key in self.positions:
            idx = self.positions.pop(key)
            if 0 <= idx < len(self.lines):
                self.lines.pop(idx)
            for k, pos in list(self.positions.items()):
                if pos > idx:
                    self.positions[k] = pos - 1
        return value

    def render(self) -> str:
        return "---\n" + "\n".join(self.lines) + "\n---\n"


def split_post(raw: str) -> tuple[FrontMatter, str]:
    """Разбирает файл поста на front matter и тело."""
    m = re.match(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?", raw, re.S)
    if not m:
        return FrontMatter(), raw
    fm = FrontMatter.parse(raw)
    return fm, raw[m.end():]


def join_post(fm: FrontMatter, body: str) -> str:
    """Собирает файл поста обратно (тело без изменений)."""
    return fm.render() + ("\n" if not body.startswith("\n") else "") + body


def read_post(path: str | Path) -> tuple[FrontMatter, str, str]:
    p = Path(path)
    if not p.is_absolute():
        p = REPO / p
    raw = p.read_text(encoding="utf-8")
    fm, body = split_post(raw)
    return fm, body, raw


def as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# Конфиг и режимы
# ---------------------------------------------------------------------------

def channel_config(channel: str) -> dict:
    """Запись канала из channels.json (источник параметров)."""
    for rec in channels_config().get("channels", []):
        if rec.get("slug") == channel:
            return rec
    raise KeyError(f"канал {channel!r} не найден в channels.json")


def profile_of(channel: str | dict) -> str:
    ch = channel if isinstance(channel, dict) else channel_config(channel)
    profile = (ch.get("format_profile") or "").strip().lower()
    if profile in ("core", "zabava", "telegram"):
        return profile
    if ch.get("platform") == "telegram":
        return "telegram"
    return "core"


def mode_of(fm: FrontMatter | dict, force_core: bool = False) -> str:
    value = fm.get("format_core") if isinstance(fm, FrontMatter) else fm.get("format_core")
    return "CORE" if (force_core or as_bool(value)) else "LEGACY"


def int_param(ch: dict, key: str, default: int) -> int:
    try:
        return int(ch.get(key, default))
    except (TypeError, ValueError):
        return default


def float_param(ch: dict, key: str, default: float) -> float:
    try:
        value = ch.get(key, default)
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# CTA: адресат, чередование, история
# ---------------------------------------------------------------------------

def cta_history_path(channel: str) -> Path:
    return channel_dir(channel) / "cta-history.json"


def load_cta_history(channel: str) -> dict:
    path = cta_history_path(channel)
    if not path.exists():
        return {"_": "История чередования cta_target (self/ainow).", "targets": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"_": "История чередования cta_target (self/ainow).", "targets": []}
    if not isinstance(data.get("targets"), list):
        data["targets"] = []
    return data


def save_cta_history(channel: str, data: dict) -> None:
    path = cta_history_path(channel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def last_cta_target(channel: str, history: dict | None = None) -> str | None:
    hist = history if history is not None else load_cta_history(channel)
    targets = hist.get("targets") or []
    for entry in reversed(targets):
        value = entry.get("target") if isinstance(entry, dict) else entry
        if value in ("self", "ainow"):
            return value
    return None


def choose_cta_target(channel: str, fm: FrontMatter | dict | None = None,
                      ch: dict | None = None, history: dict | None = None) -> tuple[str, bool]:
    """Возвращает (эффективный cta_target, нужно ли предупреждение).

    В каналах с чередованием отсутствующее поле выбирается как противоположное
    последнему значению в cta-history.json (по умолчанию self).
    """
    ch = ch or channel_config(channel)
    mode = ch.get("cta_target_mode", "self")
    raw = fm.get("cta_target") if fm is not None else None
    warning = False
    if mode == "alternate":
        if raw in ("self", "ainow"):
            return raw, False
        warning = True
        previous = last_cta_target(channel, history)
        return ("ainow" if previous == "self" else "self"), warning
    if raw == "ainow" and channel == "ainow":
        return "self", warning
    return "self", warning


def record_cta_target(channel: str, post_name: str, target: str,
                      url: str | None = None, ts: str | None = None) -> dict:
    """Добавляет запись в историю чередования CTA канала."""
    hist = load_cta_history(channel)
    hist.setdefault("targets", []).append({
        "post": Path(post_name).name,
        "target": target,
        "url": url or "",
        "ts": ts or datetime.now(MSK).isoformat(timespec="seconds"),
    })
    save_cta_history(channel, hist)
    return hist


def cta_for_target(channel: str, target: str, fm: FrontMatter | None = None,
                   ch: dict | None = None) -> tuple[str, str]:
    """(метка, URL) CTA для адресата self/ainow."""
    ch = ch or channel_config(channel)
    record = ch if target != "ainow" else channel_config("ainow")
    label = (fm.get("cta_label") if fm else None) or record.get("cta_label") or ""
    url = (fm.get("cta_url") if fm else None) or record.get("cta_url") or ""
    return label, url


def resolve_cta(channel: str, fm: FrontMatter | dict | None = None,
                ch: dict | None = None, history: dict | None = None) -> dict:
    """Полное решение по CTA: адресат, метка, URL, предупреждение."""
    ch = ch or channel_config(channel)
    target, warning = choose_cta_target(channel, fm, ch, history)
    label, url = cta_for_target(channel, target, fm if isinstance(fm, FrontMatter) else None, ch)
    return {"target": target, "label": label, "url": url, "warning": warning}


def parse_publish_window(value) -> tuple[int, int] | None:
    """Окно догона [start_hour, end_hour] из channels.json или None.

    Поддерживаются строки ``"07:30"``, ``"12:00,21:30"``, ``"09:00 Tue/Thu"``,
    список/кортеж часов и словарь ``{"start": 7, "end": 21}``.
    ``None``, ``"none"``, ``"manual"`` и пустая строка означают «без окна».
    """
    if value is None:
        return None
    if isinstance(value, dict):
        try:
            return int(value["start"]), int(value["end"])
        except (KeyError, TypeError, ValueError):
            return None
    if isinstance(value, (list, tuple)) and len(value) == 2:
        try:
            return int(value[0]), int(value[1])
        except (TypeError, ValueError):
            return None
    text = str(value).strip()
    if not text or text.lower() in ("none", "manual", "null"):
        return None
    hours = [int(h) for h in re.findall(r"(?<!\d)(\d{1,2}):\d{2}", text)]
    if not hours:
        return None
    return min(hours), max(hours)


# ---------------------------------------------------------------------------
# Реакции
# ---------------------------------------------------------------------------

def load_reactions_registry() -> dict:
    if not REACTIONS_REGISTRY.exists():
        return {"min_gap": 2, "channels": {}}
    return json.loads(REACTIONS_REGISTRY.read_text(encoding="utf-8"))


def save_reactions_registry(data: dict) -> None:
    REACTIONS_REGISTRY.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _history_names(state: dict) -> list[str]:
    out = []
    for item in state.get("history") or []:
        if isinstance(item, dict):
            value = item.get("post") or item.get("file") or item.get("name")
        else:
            value = item
        if value:
            out.append(str(value))
    return out


def reaction_gap(channel: str, ch: dict | None = None,
                 registry: dict | None = None) -> int:
    return int_param(ch or channel_config(channel), "reactions_min_gap",
                     int((registry or load_reactions_registry()).get("min_gap", 2)))


def can_use_reaction(channel: str, ch: dict | None = None,
                     registry: dict | None = None) -> tuple[bool, str]:
    """Можно ли ставить реакцию: между постами с реакциями >= min_gap постов."""
    reg = registry if registry is not None else load_reactions_registry()
    gap = reaction_gap(channel, ch, reg)
    state = (reg.get("channels") or {}).get(channel) or {}
    last = state.get("last_reaction_post")
    names = _history_names(state)
    if last in names:
        since = len(names) - 1 - names.index(last)
    elif last:
        since = 0  # старый формат реестра: считаем, что реакция была сразу
    else:
        return True, "реакций в истории канала нет"
    if since < gap:
        return False, (f"между постами с реакциями {since} постов, "
                       f"нужно минимум {gap}")
    return True, f"прошло {since} постов, минимум {gap}"


def mark_reaction_used(channel: str, post_name: str, phrase: str | None = None,
                       registry: dict | None = None) -> dict:
    """Фиксирует факт реакции после успешной публикации."""
    reg = registry if registry is not None else load_reactions_registry()
    state = (reg.setdefault("channels", {}).setdefault(channel, {}))
    state.setdefault("history", []).append({
        "post": Path(post_name).name,
        "reactions": True,
        "phrase": phrase or "",
        "ts": datetime.now(MSK).isoformat(timespec="seconds"),
    })
    state["last_reaction_post"] = Path(post_name).name
    if registry is None:
        save_reactions_registry(reg)
    return reg


def mark_post_without_reaction(channel: str, post_name: str,
                               registry: dict | None = None) -> dict:
    """Учитывает обычный пост в истории (счётчик постов между реакциями)."""
    reg = registry if registry is not None else load_reactions_registry()
    state = reg.setdefault("channels", {}).setdefault(channel, {})
    state.setdefault("history", []).append({
        "post": Path(post_name).name,
        "reactions": False,
        "ts": datetime.now(MSK).isoformat(timespec="seconds"),
    })
    if registry is None:
        save_reactions_registry(reg)
    return reg


def reaction_phrases(channel: str = "zabava") -> list[str]:
    path = channel_dir(channel) / "reactions-phrases.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [p.strip() for p in (data.get("phrases") or []) if str(p).strip()]


def recent_reaction_phrases(channel: str = "zabava", window: int = 6,
                            registry: dict | None = None) -> set[str]:
    reg = registry if registry is not None else load_reactions_registry()
    state = (reg.get("channels") or {}).get(channel) or {}
    phrases = []
    for item in state.get("history") or []:
        if isinstance(item, dict) and item.get("phrase"):
            phrases.append(item["phrase"])
    return set(phrases[-window:])


# ---------------------------------------------------------------------------
# Результат проверки
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Issue:
    code: str
    severity: str  # error | warning
    message: str

    def __str__(self) -> str:
        return f"[{self.severity}] {self.code}: {self.message}"


@dataclass
class CheckResult:
    channel: str
    profile: str
    mode: str
    cta_target: str | None = None
    post: str = ""
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, code: str, message: str) -> None:
        self.issues.append(Issue(code, "error", message))

    def warning(self, code: str, message: str) -> None:
        self.issues.append(Issue(code, "warning", message))

    def extend(self, other: "CheckResult") -> None:
        self.issues.extend(other.issues)

    def to_dict(self) -> dict:
        return {
            "channel": self.channel,
            "profile": self.profile,
            "mode": self.mode,
            "cta_target": self.cta_target,
            "post": self.post,
            "ok": self.ok,
            "errors": [str(i) for i in self.errors],
            "warnings": [str(i) for i in self.warnings],
        }

    def report(self) -> str:
        lines = [f"пост: {self.post}", f"канал: {self.channel}",
                 f"профиль: {self.profile}, режим: {self.mode}",
                 f"cta_target: {self.cta_target or '-'}"]
        for issue in self.issues:
            lines.append(str(issue))
        lines.append(f"итог: ошибок {len(self.errors)}, предупреждений {len(self.warnings)}; "
                     f"{'OK' if self.ok else 'FAIL'}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Текстовые и медиа-утилиты
# ---------------------------------------------------------------------------

def plain_text(md: str) -> str:
    """Текст для LanguageTool: без ссылок, выделений, цитат и заголовков."""
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", md)
    t = re.sub(r"[*_`]{1,3}", "", t)
    t = re.sub(r"^>\s?", "", t, flags=re.M)
    t = re.sub(r"^#{1,6}\s?", "", t, flags=re.M)
    return t


def blocks(text: str) -> list[list[str]]:
    """Смысловые блоки: группы непустых строк, разделённые пустыми."""
    out: list[list[str]] = []
    cur: list[str] = []
    for line in text.splitlines():
        if line.strip():
            cur.append(line)
        elif cur:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def is_subheading(line: str) -> bool:
    """Полностью жирная строка (возможно, с эмодзи/номером впереди)."""
    s = line.strip()
    if not s or s.startswith(">"):
        return False
    return bool(re.fullmatch(r"[\W\d\ufe0f\u20e3]*\*\*[^*]+\*\*[\W\d\ufe0f\u20e3]*", s))


def is_reaction_line(line: str) -> bool:
    return bool(REACTION_RE.search(line)) and not line.lstrip().startswith(">")


def inline_bold_count(text: str) -> int:
    total = 0
    for line in text.splitlines():
        if is_subheading(line) or line.lstrip().startswith(">"):
            continue  # подзаголовки и CTA/цитаты в бюджет абзацев не входят
        total += len(re.findall(r"\*\*[^*]+\*\*", line))
    return total


def resolve_media_path(name: str | None) -> Path | None:
    if not name:
        return None
    candidate = Path(name)
    if not candidate.is_absolute():
        candidate = REPO / candidate
    if candidate.exists():
        return candidate
    if "/" not in str(name) and "\\" not in str(name):
        for sub in ("local/images", "local/media-cache"):
            alt = REPO / sub / name
            if alt.exists():
                return alt
    return None


def media_fields(fm: FrontMatter, resolver: Callable | None = None) -> dict:
    """Сводка по медиа поста: одиночное / альбом / нет."""
    find = resolver or resolve_media_path
    singles = []
    for key, kind in (("video_file", "video"), ("image_file", "image")):
        value = fm.get(key)
        if value:
            singles.append((kind, value, find(value)))
    raw_album = fm.get("image_files") or ""
    album = [x.strip() for x in re.split(r"[|,]", raw_album) if x.strip()]
    total = len(singles) + len(album)
    return {
        "singles": singles,
        "album": album,
        "album_paths": [find(x) for x in album],
        "count": total,
        "single": singles[0] if total == 1 and singles else None,
        "is_album": total >= 2,
    }


def measure_media(path: str | Path) -> tuple[int, int, float] | None:
    """(width, height, aspect) для изображения или видео; None — измерить нельзя."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"):
        try:
            from PIL import Image  # noqa: WPS433
            with Image.open(p) as im:
                w, h = im.size
            return w, h, (w / h if h else 0.0)
        except Exception:  # noqa: BLE001
            return None
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", str(p)],
            capture_output=True, text=True, timeout=20)
        match = re.search(r"(\d+)[,:\s]+(\d+)", proc.stdout or "")
        if match:
            w, h = int(match.group(1)), int(match.group(2))
            if w and h:
                return w, h, w / h
    except Exception:  # noqa: BLE001
        pass
    return None


# ---------------------------------------------------------------------------
# Базовые проверки (CORE и LEGACY)
# ---------------------------------------------------------------------------

def check_forbidden(text: str, result: CheckResult) -> None:
    try:
        from .forbidden_orgs import assert_no_forbidden_orgs
    except ImportError:
        from shared.forbidden_orgs import assert_no_forbidden_orgs  # type: ignore
    try:
        assert_no_forbidden_orgs(text)
    except SystemExit as exc:
        result.error("FORBIDDEN_ORG", str(exc))


def check_spelling(text: str, fm: FrontMatter, channel: str, result: CheckResult) -> None:
    try:
        from .text_check import check_text as lt_check, format_issue
    except ImportError:
        from shared.text_check import check_text as lt_check, format_issue  # type: ignore
    ignore = {w.strip() for w in str(fm.get("spell_ignore") or "").split(",") if w.strip()}
    ign_path = channel_dir(channel) / "spell-ignore.json"
    if ign_path.exists():
        try:
            data = json.loads(ign_path.read_text(encoding="utf-8"))
            ignore |= {w.strip() for w in data.get("words", []) if w.strip()}
        except (OSError, json.JSONDecodeError):
            pass
    spell = lt_check(plain_text(text), ignore_words=sorted(ignore))
    if spell.get("status") == "unavailable":
        result.warning("SPELL_UNAVAILABLE", str(spell.get("message", "сервис недоступен")))
        return
    for issue in spell.get("errors") or []:
        result.error("SPELL", format_issue(issue))
    for issue in spell.get("warnings") or []:
        result.warning("SPELL_STYLE", format_issue(issue))


def check_status(fm: FrontMatter, result: CheckResult, *, for_publish: bool,
                 mode: str) -> None:
    status = (fm.get("status") or "").strip().lower()
    if status in ("deleted", "to_delete"):
        result.error("STATUS", f"канал/пост со статусом {status!r} не публикуется")
    elif status == "published":
        result.error("STATUS", "пост уже опубликован (status: published)")
    elif status == "hold":
        result.error("STATUS", "пост на паузе (hold) — снятие только по команде владельца")
    elif status in ("draft", ""):
        if for_publish or mode == "CORE":
            result.error("STATUS", "для публикации нужен status: approved "
                                   f"(сейчас {status or 'не задан'!r})")
        else:
            result.warning("STATUS", f"неопубликованный пост (status: {status or 'не задан'})")


def check_length(text: str, ch: dict, result: CheckResult) -> None:
    hard = int_param(ch, "length_hard", DEFAULT_LENGTH_HARD)
    soft = int_param(ch, "length_soft", DEFAULT_LENGTH_SOFT)
    if profile_of(ch) == "telegram":
        hard = min(hard, TELEGRAM_CAPTION_MAX)
    n = len(text)
    if n > hard:
        result.error("LENGTH", f"длина {n} > {hard}")
    elif n > soft:
        result.warning("LENGTH_SOFT", f"длина {n} выше комфортного лимита {soft} (жёсткий {hard})")


def check_media_aspect(fm: FrontMatter, ch: dict, result: CheckResult, *,
                       require_exists: bool = False,
                       resolver: Callable | None = None) -> None:
    if profile_of(ch) == "zabava":
        return
    if as_bool(fm.get("media_aspect_exempt")):
        result.warning("MEDIA_EXEMPT", "media_aspect_exempt: проверка пропорций отключена")
        return
    minimum = float_param(ch, "media_aspect_min", DEFAULT_MEDIA_MIN)
    if minimum <= 0:
        return
    info = media_fields(fm, resolver=resolver)
    if info["count"] == 0:
        allowed = bool(ch.get("allow_text_only")) or ch.get("slug") == "catden"
        if not allowed and require_exists:
            result.error("MEDIA_MISSING", "нет медиа (image_file/video_file/image_files)")
        return
    if info["is_album"]:
        max_images = int_param(ch, "max_images", 9)
        if len(info["album"]) > max_images:
            result.error("ALBUM_LIMIT", f"в альбоме {len(info['album'])} файлов, максимум {max_images}")
        return  # альбомы от 2 файлов вне правила пропорций
    kind, name, path = info["single"]
    if path is None:
        msg = f"медиа не найдено: {name}"
        (result.error if require_exists else result.warning)("MEDIA_MISSING", msg)
        return
    measured = measure_media(path)
    if measured is None:
        result.warning("MEDIA_MEASURE", f"не удалось измерить пропорции {path.name} — проверка вручную")
        return
    w, h, ar = measured
    if ar + 1e-6 < minimum:
        result.error("MEDIA_ASPECT",
                     f"одиночное медиа {path.name} {w}x{h}, соотношение {ar:.3f} "
                     f"< {minimum:.2f}; нужно {minimum:.2f} или шире")
    if kind == "video":
        result.warning("MEDIA_VIDEO", f"проверены пропорции видео {path.name}: {ar:.3f}")


def check_legacy_cta(text: str, ch: dict, result: CheckResult) -> None:
    marker = ("Подпишись на канал" if profile_of(ch) == "zabava"
              else "Подписывайтесь на")
    if marker not in text:
        result.error("CTA_MISSING", "нет CTA (обязателен и в legacy-режиме)")


# ---------------------------------------------------------------------------
# CORE: структура
# ---------------------------------------------------------------------------

def check_headline(text: str, ch: dict, result: CheckResult, *, emoji: bool = False) -> str:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        result.error("HEADLINE", "нет заголовка")
        return ""
    first = lines[0].strip()
    m = re.fullmatch(r"\*\*([^*]+)\*\*", first)
    if not m and emoji:
        # Канон telegram: жирный заголовок с ведущим эмодзи (🎬 **Заголовок**).
        m = re.fullmatch(r"[\W\d\ufe0f\u20e3]*\*\*([^*]+)\*\*[\W\d\ufe0f\u20e3]*", first)
    if not m:
        result.error("HEADLINE", "первая строка должна быть жирным заголовком: **Заголовок**")
        return ""
    title = m.group(1).strip()
    limit = int_param(ch, "headline_max", DEFAULT_HEADLINE_MAX)
    if len(title) > limit:
        result.error("HEADLINE_LEN", f"заголовок {len(title)} знаков > {limit}")
    if title.endswith("."):
        result.error("HEADLINE_DOT", "заголовок не должен заканчиваться точкой")
    if first.lstrip().startswith("#"):
        result.error("HEADLINE_MARKDOWN", "запрещены заголовки markdown (###)")
    if emoji and not EMOJI_RE.search(first):
        result.warning("HEADLINE_EMOJI", "заголовок telegram-поста должен содержать эмодзи")
    return title


def check_air(text: str, result: CheckResult) -> None:
    lines = text.splitlines()
    meaningful = [i for i, ln in enumerate(lines) if ln.strip()]
    if not meaningful:
        return
    first = meaningful[0]
    if first + 1 >= len(lines) or lines[first + 1].strip():
        result.error("AIR_HEADLINE", "после главного заголовка нужна пустая строка")
    for idx, i in enumerate(meaningful[:-1]):
        if i == first:
            continue  # главный заголовок обработан отдельно
        j = meaningful[idx + 1]
        cur, nxt = lines[i], lines[j]
        if is_subheading(cur):
            if j == i + 1:
                continue  # под подзаголовком воздуха нет — это норма
            result.error("AIR_SUBHEAD", f"пустая строка под подзаголовком: {cur.strip()[:60]}")
            continue
        if j == i + 1:
            if cur.lstrip().startswith(">") and nxt.lstrip().startswith(">"):
                continue  # цитатный блок кода/промпта
            if nxt.lstrip().startswith(ALLOWED_MARKERS) and (
                    cur.lstrip().startswith(ALLOWED_MARKERS) or is_subheading(cur)):
                continue
            result.error("AIR_BLOCK", f"нет пустой строки между блоками: "
                                      f"{cur.strip()[:40]!r} / {nxt.strip()[:40]!r}")


def check_markup(text: str, result: CheckResult) -> None:
    patterns = {
        "MARKUP_LIST": (r"^\s*(?:[-*+]|\d+\.)\s+", "markdown-список"),
        "MARKUP_TABLE": (r"^\s*\|.*\||\|\s*:?-{3,}:?\s*\|", "таблица markdown"),
        "MARKUP_HEAD": (r"^\s*#{1,6}\s+", "заголовок markdown"),
        "MARKUP_TICK": (r"`", "моноширинный backtick"),
    }
    for code, (rx, label) in patterns.items():
        matches = [ln.strip() for ln in text.splitlines() if re.search(rx, ln)]
        if matches:
            result.error(code, f"запрещённая вёрстка ({label}): {matches[:2]}")


def check_bold(text: str, ch: dict, result: CheckResult) -> None:
    limit = int_param(ch, "bold_budget", DEFAULT_BOLD_BUDGET)
    count = inline_bold_count(text)
    if count > limit:
        result.error("BOLD_BUDGET", f"жирных выделений в абзацах {count} > {limit}")


def check_cta_position(text: str, fm: FrontMatter, ch: dict, result: CheckResult,
                       *, expect: dict | None = None) -> dict:
    """CTA-цитата предпоследним блоком, вопрос последним, ссылка — адресату."""
    expect = expect or resolve_cta(ch.get("slug", ""), fm, ch)
    group_list = blocks(text)
    cta_idx = None
    cta_match = None
    for idx, group in enumerate(group_list):
        for line in group:
            m = CTA_CORE_RE.match(line.strip())
            if m:
                cta_idx, cta_match = idx, m
                break
        if cta_idx is not None:
            break
    if cta_match is None:
        result.error("CTA_FORMAT",
                     "нет CTA-цитаты вида > **Подписывайтесь на [метка](url)** — фраза")
        return {}
    label, url, phrase = cta_match.group(1), cta_match.group(2), cta_match.group(3).strip()
    expected_label, expected_url = expect.get("label"), expect.get("url")
    if expected_label and label != expected_label:
        result.error("CTA_LABEL", f"метка CTA {label!r} != {expected_label!r}")
    if expected_url and url != expected_url:
        result.error("CTA_TARGET_URL",
                     f"ссылка CTA {url!r} не соответствует адресату "
                     f"{expect.get('target')!r} ({expected_url!r})")
    if not phrase:
        result.error("CTA_PHRASE", "пустая фраза CTA")
    last = len(group_list) - 1
    reaction_between = (last >= cta_idx + 2
                        and len(group_list[cta_idx + 1]) == 1
                        and is_reaction_line(group_list[cta_idx + 1][0]))
    want_idx = last - 2 if reaction_between else last - 1
    if cta_idx != want_idx:
        result.error("CTA_POSITION",
                     f"CTA должен быть предпоследним блоком (блок {cta_idx + 1} из {last + 1}, "
                     f"последний — вопрос)")
    if last < 0:
        return {}
    question_group = group_list[last]
    question = " ".join(question_group).strip()
    if len(question_group) != 1 or "?" not in question:
        result.error("QUESTION", "последний блок — одна строка-вопрос со '?'")
    elif re.fullmatch(r"а вы что думаете\??", question, re.I):
        result.warning("QUESTION_CLICHE", "дежурный вопрос «а вы что думаете?» не приветствуется")
    if reaction_between:
        check_reaction_interval(group_list[cta_idx + 1], fm, ch, result)
    return {"label": label, "url": url, "phrase": phrase,
            "reaction": group_list[cta_idx + 1][0] if reaction_between else None}


def check_reaction_interval(reaction_block: list[str] | str, fm: FrontMatter,
                            ch: dict, result: CheckResult) -> None:
    text = reaction_block if isinstance(reaction_block, str) else " ".join(reaction_block)
    if len(text.splitlines()) > 1:
        result.error("REACTION_LINES", "призыв к реакциям — не более одной строки")
    if not is_reaction_line(text):
        result.warning("REACTION_FORMAT", "строка между CTA и вопросом не похожа на призыв к реакциям")
    allowed, reason = can_use_reaction(ch.get("slug", ""), ch)
    if not allowed:
        result.error("REACTION_GAP", f"интервал реакций нарушен: {reason}")


def check_interlinks(text: str, ch: dict, result: CheckResult, *, target_url: str = "",
                     cta_url: str = "") -> int:
    urls = [u for u in LINK_RE.findall(text) if u != cta_url and u != target_url]
    count = sum(1 for u in urls if POST_LINK_RE.search(u))
    rules = ch.get("interlink") or {}
    try:
        minimum, maximum = int(rules.get("min", 0)), int(rules.get("max", 0))
    except (TypeError, ValueError):
        minimum, maximum = 0, 0
    if count < minimum or count > maximum:
        result.error("INTERLINK",
                     f"перелинковок {count}, нужно от {minimum} до {maximum}")
    return count


def check_cta_target_field(fm: FrontMatter, ch: dict, result: CheckResult,
                           expect: dict) -> None:
    raw = fm.get("cta_target")
    mode = ch.get("cta_target_mode", "self")
    if raw is not None and raw not in ("self", "ainow"):
        result.error("CTA_TARGET_FIELD", f"cta_target={raw!r}, допустимо self или ainow")
    if mode == "alternate" and expect.get("warning"):
        result.warning("CTA_TARGET_MISSING", CTA_MISSING_WARNING)
    if mode == "self" and raw not in (None, "self", ch.get("slug")):
        result.error("CTA_TARGET_FIELD",
                     f"для канала {ch.get('slug')} допустим только cta_target: self")


def check_core(text: str, fm: FrontMatter, ch: dict, result: CheckResult) -> dict:
    expect = resolve_cta(ch.get("slug", ""), fm, ch)
    result.cta_target = expect["target"]
    check_headline(text, ch, result)
    check_air(text, result)
    check_markup(text, result)
    check_bold(text, ch, result)
    check_cta_target_field(fm, ch, result, expect)
    info = check_cta_position(text, fm, ch, result, expect=expect)
    check_interlinks(text, ch, result, target_url=expect["url"],
                     cta_url=fm.get("cta_url") or "")
    if ch.get("slug") == "na100":
        extra = [u for u in LINK_RE.findall(text) if u != expect["url"]]
        if extra:
            result.error("NA100_LINKS", f"внешние ссылки запрещены, кроме CTA: {extra[:2]}")
    return info


# ---------------------------------------------------------------------------
# Неядровые профили
# ---------------------------------------------------------------------------

def strip_generated_blocks(text: str, channel: str = "zabava") -> tuple[str, dict]:
    """Убирает автоматические блоки (реакция/CTA), чтобы мерить бюджет тела."""
    lines = text.splitlines()
    cta_re = CTA_ZABAVA_RE if channel == "zabava" else CTA_TELEGRAM_RE
    cta_idx, cta = None, None
    for idx, line in enumerate(lines):
        m = cta_re.match(line.strip())
        if m:
            cta_idx, cta = idx, m
            break
    if cta_idx is None:
        # Черновики иногда содержат CTA с запятой вместо тире — всё равно это
        # генерируемый блок публикатора, а не бюджет тела.
        marker = "Подпишись на" if channel == "zabava" else "Подписывайтесь на"
        for idx, line in enumerate(lines):
            if marker in line and "](" in line:
                cta_idx = idx
                break
    reaction = None
    body_lines = lines[:cta_idx] if cta_idx is not None else list(lines)
    while body_lines and not body_lines[-1].strip():
        body_lines.pop()
    if body_lines:
        last = body_lines[-1].strip()
        if is_reaction_line(last) and (last in reaction_phrases(channel) or "🔥" in last):
            reaction = last
            body_lines = body_lines[:-1]
            while body_lines and not body_lines[-1].strip():
                body_lines.pop()
    return "\n".join(body_lines).strip(), {
        "cta": cta, "cta_index": cta_idx, "reaction": reaction,
        "lines": lines, "all_blocks": blocks(text)}


def check_zabava(text: str, fm: FrontMatter, ch: dict, result: CheckResult,
                 mode: str = "CORE") -> None:
    body, gen = strip_generated_blocks(text, "zabava")
    max_len = int_param(ch, "body_max", DEFAULT_BODY_MAX)
    max_lines = int_param(ch, "body_lines_max", DEFAULT_BODY_LINES)
    if not body:
        # D4: существующие посты не пересекаются массово. У legacy-поста zabava
        # контентом может быть само видео, а текст сводится к CTA — это не блокер.
        if mode == "LEGACY":
            result.warning("BODY_EMPTY_LEGACY",
                           "у legacy-поста zabava нет текста тела (видео + CTA)")
        else:
            result.error("BODY_EMPTY", "пустое тело поста zabava")
    if len(body) > max_len:
        result.error("BODY_LEN", f"тело {len(body)} знаков > {max_len}")
    lines = body.splitlines()
    if len(lines) > max_lines:
        result.error("BODY_LINES", f"тело {len(lines)} строк > {max_lines}")
    if body.endswith("."):
        result.error("BODY_DOT", "текст zabava не должен заканчиваться точкой")
    for bad, label in (("#", "хештег"), ("**", "markdown-разметка"),
                       ("](", "markdown-ссылка"), ("`", "backtick"),
                       ("http", "ссылка")):
        haystack = body.lower() if bad == "http" else body
        if bad in haystack:
            result.error("BODY_MARKUP", f"в теле запрещён {label}")
    emojis = len(EMOJI_RE.findall(body.replace("\ufe0f", "")))
    if emojis > 2:
        result.error("BODY_EMOJI", f"эмодзи в теле: {emojis}, максимум 2")
    phrase = gen["cta"].group(3).strip() if gen["cta"] else None
    if gen["cta"]:
        label, url = gen["cta"].group(1), gen["cta"].group(2)
        expected_label = ch.get("cta_label") or ""
        expected_url = ch.get("cta_url") or ""
        if label != expected_label or url != expected_url:
            result.error("ZABAVA_CTA", f"CTA {label!r} {url!r} != {expected_label!r} {expected_url!r}")
        if not phrase or "🎬" not in gen["cta"].group(0):
            result.error("ZABAVA_CTA", "CTA: «Подпишись на канал **Забавное** — <фраза> 🎬»")
        nonempty = [i for i, ln in enumerate(gen["lines"]) if ln.strip()]
        if not nonempty or gen["cta_index"] != nonempty[-1]:
            result.error("ZABAVA_CTA_POSITION", "CTA должен быть последней строкой")
    else:
        result.warning("ZABAVA_CTA_AUTO", "CTA будет добавлен публикатором автоматически")
    if gen["reaction"]:
        known = set(reaction_phrases("zabava"))
        if known and gen["reaction"] not in known:
            result.warning("ZABAVA_REACTION_PHRASE", "фраза реакции не из reactions-phrases.json")
        allowed, reason = can_use_reaction("zabava", ch)
        if not allowed:
            result.error("REACTION_GAP", f"интервал реакций нарушен: {reason}")
    cap = int_param(ch, "daily_cap", 1)
    if cap > 1:
        result.warning("ZABAVA_CAP", f"daily_cap={cap} в конфиге, ожидается 1")


def check_telegram(text: str, fm: FrontMatter, ch: dict, result: CheckResult) -> None:
    expect = resolve_cta(ch.get("slug", ""), fm, ch)
    result.cta_target = expect["target"]
    body, gen = strip_generated_blocks(text, ch.get("slug", "tg_neuro"))
    check_headline(text, ch, result, emoji=True)
    # ссылка на конкретный пост ainow внутри текста
    ainow_links = [u for u in LINK_RE.findall(text)
                   if "channel_ainow/" in u and u != expect["url"]]
    if not ainow_links:
        result.error("TG_INTERLINK", "нужна минимум 1 ссылка на опубликованный пост ainow")
    cta_lines = [ln.strip() for ln in text.splitlines()
                 if "Подписывайтесь на" in ln]
    if not cta_lines:
        result.error("TG_CTA", "нет CTA «**Подписывайтесь на AI** — фраза»")
    else:
        cta_line = cta_lines[-1]
        if cta_line.startswith(">"):
            result.error("TG_CTA_QUOTE", "CTA telegram не должен быть цитатой (без '> ')")
        if expect["url"] and expect["url"] not in cta_line:
            result.error("TG_CTA_URL", f"в CTA нет ссылки {expect['url']}")
        nonempty = [i for i, ln in enumerate(text.splitlines()) if ln.strip()]
        last_idx = nonempty[-1] if nonempty else -1
        if text.splitlines()[last_idx].strip() != cta_line:
            result.error("TG_CTA_POSITION", "CTA должен быть последней строкой")
    if fm.get("hold"):
        result.error("HOLD", "пост на паузе (hold)")
    reaction_lines = [ln.strip() for ln in body.splitlines()
                      if is_reaction_line(ln)]
    if reaction_lines:
        if len(reaction_lines) > 1:
            result.error("REACTION_LINES", "призыв к реакциям — не более одной строки")
        allowed, reason = can_use_reaction(ch.get("slug", ""), ch)
        if not allowed:
            result.error("REACTION_GAP", f"интервал реакций нарушен: {reason}")
    if fm.get("button_url") and fm.get("button_url") != expect["url"]:
        result.warning("TG_BUTTON", "button_url отличается от cta_url канала")


# ---------------------------------------------------------------------------
# Канальные дополнения (только то, чего нет в §0)
# ---------------------------------------------------------------------------

def digest_item_blocks(body: str) -> list[str]:
    idx = [m.start() for m in re.finditer(r"^[1-5]\ufe0f?\u20e3", body, re.M)]
    return [body[idx[i]: (idx[i + 1] if i + 1 < len(idx) else len(body))]
            for i in range(len(idx))]


def check_ainow_extras(text: str, result: CheckResult) -> None:
    if not re.search(r"промпт|чек-лист|шаг\s*1|1️⃣|2️⃣|3️⃣", text, re.I):
        result.warning("AINOW_OUTPUT", "нет «выхода»: промпта, чек-листа или шагов")
    is_review = bool(re.search(r"бесплатн|сервис|инструмент|платформ", text, re.I))
    if is_review and not re.search(r"⚠|лимит|не работает|блокир|ограничен", text, re.I):
        result.warning("AINOW_LIMITS", "похоже на обзор инструмента, но нет предупреждения об ограничениях")


def check_digest_extras(text: str, result: CheckResult, *, require_question: bool = True) -> None:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    hook = lines[0].strip("* ") if lines else ""
    if 0 < len(hook) < 40:
        result.warning("DIGEST_HOOK", f"хук {len(hook)} знаков — ниже ориентира 40")
    items = digest_item_blocks(text)
    if len(items) != 5:
        result.error("DIGEST_ITEMS", f"пунктов {len(items)}, должно быть 5")
    what, why = text.count("Что случилось"), text.count("Почему важно")
    if what != 5 or why != 5:
        result.error("DIGEST_STRUCTURE", f"«Что случилось» — {what}, «Почему важно» — {why} (нужно по 5)")
    subs = re.findall(r"^[1-5]\ufe0f?\u20e3\s+\*\*(.+?)\*\*\s*$", text, re.M)
    with_digit = sum(1 for s in subs if re.search(r"\d", s))
    if with_digit < 2:
        result.error("DIGEST_DIGITS", f"цифра в подзаголовке у {with_digit} из 5, нужно ≥2")
    for n, block in enumerate(items, 1):
        clean = re.sub(r"^[1-5]\ufe0f?\u20e3\s+\*\*.+?\*\*\s*$", "", block, flags=re.M)
        clean = clean.split("> ")[0]
        if len(re.findall(r"\*\*[^*]+\*\*", clean)) > 2:
            result.error("DIGEST_BOLD", f"пункт {n}: больше двух выделений жирным")
        if len(block) > 750:
            result.error("DIGEST_ITEM_LEN", f"пункт {n}: {len(block)} знаков > 750")
    if "Итог дня" not in text:
        result.error("DIGEST_SUMMARY", "нет блока «Итог дня»")
    else:
        summary = text.split("Итог дня", 1)[1].split("\n\n")[0][:400]
        if (summary.count(",") + summary.count(";") >= 3
                and not re.search(r"поэтому|значит|отсюда", summary, re.I)):
            result.warning("DIGEST_SUMMARY_STYLE", "итог похож на перечисление, нужна причинная связка")
    if require_question and not re.search(r"\?\s*$", text.strip()):
        result.error("DIGEST_QUESTION", "в каждом новом выпуске na100 обязателен вопрос последним блоком")
    if "Фото:" not in text and "Иллюстрация:" not in text:
        result.error("DIGEST_ATTRIBUTION", "нет атрибуции «Фото:» / «Иллюстрация:»")


def check_series_rhythm(channel: str = "catden", date_from: str = "",
                        date_to: str = "", ch: dict | None = None) -> dict:
    """Ритм пар catden: альбом-карусель выходит до текстового поста серии."""
    ch = ch or channel_config(channel)
    series: dict[str, list[dict]] = {}
    base = post_dir(channel)
    for path in sorted(base.glob("*.md")):
        date = path.name[:10]
        if date_from and date < date_from:
            continue
        if date_to and date > date_to:
            continue
        fm, _ = split_post(path.read_text(encoding="utf-8"))
        parts = path.stem.split("-")
        default_name = parts[3] if len(parts) > 3 else path.stem
        name = fm.get("series") or default_name
        files = fm.get("image_files") or fm.get("image_file") or ""
        names = [x.strip() for x in re.split(r"[|,]", files) if x.strip()]
        album = bool(fm.get("image_files")) or bool(re.search(r"-img\d+$", path.stem))
        series.setdefault(name, []).append({"date": date, "file": path.name,
                                            "album": album, "images": len(names),
                                            "status": fm.get("status", "")})
    bad, lonely, ok = [], [], 0
    for name, posts in sorted(series.items()):
        albums = sorted([p for p in posts if p["album"]], key=lambda p: p["date"])
        texts = sorted([p for p in posts if not p["album"]], key=lambda p: p["date"])
        if not albums:
            lonely.append((name, [p["date"] for p in texts]))
            continue
        if not texts:
            continue
        if albums[0]["date"] < texts[0]["date"]:
            ok += 1
        else:
            bad.append({"series": name, "album": albums[0], "post": texts[0],
                        "extra_albums": [p["date"] for p in albums[1:]]})
    return {"channel": channel, "ok": ok, "bad": bad, "lonely": lonely,
            "pairs": ok + len(bad)}


def recent_published(channel: str, limit: int = 2,
                     plan_path: str | Path | None = None) -> list[dict]:
    """Последние опубликованные посты канала (новые сверху), с флагом реакций."""
    found: list[dict] = []

    def stamp(value: str | None) -> datetime:
        if not value:
            return datetime.min.replace(tzinfo=MSK)
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return datetime.min.replace(tzinfo=MSK)
        return dt.astimezone(MSK) if dt.tzinfo else dt.replace(tzinfo=MSK)

    for path in post_dir(channel).glob("*.md"):
        fm, _ = split_post(path.read_text(encoding="utf-8"))
        if fm.get("status") != "published":
            continue
        found.append({"source": "post", "file": path.name,
                      "published_at": fm.get("published_at") or "",
                      "dt": stamp(fm.get("published_at")),
                      "reactions": as_bool(fm.get("reactions"))})
    if plan_path:
        plan_file = Path(plan_path)
        if not plan_file.is_absolute():
            plan_file = REPO / plan_file
        if plan_file.exists():
            try:
                plan = json.loads(plan_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                plan = {}
            for item in plan.get("posts") or []:
                if item.get("status") != "published":
                    continue
                found.append({"source": "plan", "file": str(item.get("file") or ""),
                              "published_at": item.get("published_at") or "",
                              "dt": stamp(item.get("published_at")),
                              "reactions": as_bool(item.get("reactions"))})
    found.sort(key=lambda x: x["dt"], reverse=True)
    return found[:limit]


def published_today(channel: str, plan_path: str | Path | None = None,
                    now: datetime | None = None) -> list[dict]:
    """Публикации канала за текущие сутки МСК (front matter + план)."""
    today = (now or datetime.now(MSK)).astimezone(MSK).date()
    found: list[dict] = []

    def within(value: str | None) -> bool:
        if not value:
            return False
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return False
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=MSK)
        return dt.astimezone(MSK).date() == today

    for path in post_dir(channel).glob("*.md"):
        fm, _ = split_post(path.read_text(encoding="utf-8"))
        if fm.get("status") == "published" and within(fm.get("published_at")):
            found.append({"source": "post", "file": path.name,
                          "published_at": fm.get("published_at"),
                          "reactions": as_bool(fm.get("reactions"))})
    if plan_path:
        plan_file = Path(plan_path)
        if not plan_file.is_absolute():
            plan_file = REPO / plan_file
        if plan_file.exists():
            try:
                plan = json.loads(plan_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                plan = {}
            for item in plan.get("posts") or []:
                if item.get("status") == "published" and within(item.get("published_at")):
                    found.append({"source": "plan", "file": str(item.get("file") or ""),
                                  "published_at": item.get("published_at"),
                                  "id": item.get("id")})
    return found


# ---------------------------------------------------------------------------
# Главная точка входа
# ---------------------------------------------------------------------------

def check_post(path: str | Path | None = None, *, channel: str | None = None,
               text: str | None = None, fm: FrontMatter | dict | None = None,
               force_core: bool = False, for_publish: bool = False,
               check_media: bool = True, check_spellcheck: bool = True,
               resolve_media_path_fn: Callable | None = None,
               extras: bool = True, post_name: str | None = None) -> CheckResult:
    """Проверяет пост и возвращает CheckResult (никогда не меняет файл)."""
    if text is not None:
        if isinstance(fm, FrontMatter):
            fm_read = fm
        elif isinstance(fm, dict):
            fm_read = FrontMatter.from_dict(fm)
        elif path is not None:
            fm_read, _, _ = read_post(path)
        else:
            fm_read = FrontMatter()
        body = text
        name = post_name or (Path(path).name if path is not None else "<text>")
    elif path is not None:
        fm_read, body, _ = read_post(path)
        name = post_name or Path(path).name
    else:
        raise ValueError("нужен path или text")
    if not isinstance(fm_read, FrontMatter):
        fm_read = FrontMatter.parse(str(fm_read or ""))
    channel = channel or (fm_read.get("channel") or "")
    if not channel:
        raise ValueError("не задан канал (--channel или front matter channel)")
    ch = channel_config(channel)
    mode = mode_of(fm_read, force_core)
    profile = profile_of(ch)
    result = CheckResult(channel=channel, profile=profile, mode=mode,
                         cta_target=fm_read.get("cta_target"), post=name)
    if post_name:
        result.post = post_name

    check_status(fm_read, result, for_publish=for_publish, mode=mode)
    check_length(body, ch, result)
    check_forbidden(body, result)
    if check_spellcheck:
        check_spelling(body, fm_read, channel, result)
    if check_media:
        check_media_aspect(fm_read, ch, result, require_exists=for_publish,
                           resolver=resolve_media_path_fn)

    if mode == "LEGACY" and profile == "core":
        # Старые посты ядра: только критический минимум, без структурных правил.
        check_legacy_cta(body, ch, result)
        return result
    # zabava и tg_neuro живут по своему канону независимо от поля format_core.

    if profile == "core":
        check_core(body, fm_read, ch, result)
        if extras:
            if channel == "ainow":
                check_ainow_extras(body, result)
            elif channel == "na100":
                check_digest_extras(body, result, require_question=True)
    elif profile == "zabava":
        check_zabava(body, fm_read, ch, result, mode=mode)
    elif profile == "telegram":
        check_telegram(body, fm_read, ch, result)
    return result


def check_media_aspect_wrapper(fm: FrontMatter, ch: dict, result: CheckResult,
                               *, require_exists: bool = False,
                               resolver: Callable | None = None) -> None:
    """Тонкая обёртка для инструментов (media_aspect.py, publishers)."""
    check_media_aspect(fm, ch, result, require_exists=require_exists, resolver=resolver)


# Публичные алиасы для инструментов и тестов.
check_media = check_media_aspect
check = check_post
validate_post = check_post
check_file = check_post
check_text_post = check_post


def summarize(result: CheckResult) -> str:
    """Однострочная ASCII-сводка для консоли (cp1251-safe)."""
    return (f"FORMAT_CORE channel={result.channel} profile={result.profile} "
            f"mode={result.mode} errors={len(result.errors)} "
            f"warnings={len(result.warnings)} status={'OK' if result.ok else 'FAIL'}")
