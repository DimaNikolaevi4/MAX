# Сбор новостей по темам: RSS (stdlib) -> фильтр по ключевым словам ->
# сборка текста дайджеста (markdown MAX, <= 4000 символов).
# Кириллицу в консоль не печатаем (cp1251 Windows).
from __future__ import annotations

import datetime
import html
import re
import ssl
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET

FEEDS = {
    "habr": "https://habr.com/ru/rss/news/?fl=ru",
    "vc": "https://vc.ru/rss/all",
    "lenta": "https://lenta.ru/rss/",
}

# Синонимы тем: универсальный словарь для MVP; темы участников расширяются им же.
SYNONYMS = {
    "ии": ["ии", "искусственн", "нейросет", "llm", "gpt", "машинн", "ai "],
    "нейросети": ["нейросет", "нейрон", "llm", "gpt", "ии", "искусственн"],
    "айти": ["it-", "айти", "разработчик", "программист", " стартап"],
}


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", html.unescape(text or ""))
    return text.replace("\u00a0", " ")


def strip_html(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment or "")
    text = re.sub(r"\s+", " ", _normalize(text)).strip()
    return text


def theme_keywords(theme: str) -> list[str]:
    base = _normalize(theme).strip().lower()
    keys = {base}
    for k, vals in SYNONYMS.items():
        if base == k or base in k or k in base:
            keys.update(vals)
    return sorted(keys)


def fetch_feed(url: str) -> list[dict]:
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8.13.0"})
    with urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=25) as resp:
        xml = resp.read()
    root = ET.fromstring(xml)
    items = []
    for elem in root.iter():
        if elem.tag.rsplit("}", 1)[-1] != "item":
            continue
        title = link = description = ""
        pub = ""
        for child in elem:
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "title":
                title = _normalize(child.text or "")
            elif tag == "link":
                link = (child.text or "").strip()
            elif tag == "description":
                description = strip_html(child.text or "")
            elif tag == "pubDate":
                pub = (child.text or "").strip()
        if title and link:
            items.append({"title": title, "link": link, "description": description, "pub": pub})
    return items


def keyword_hit(keyword: str, haystack: str) -> bool:
    """Короткие токены (ии, ai, gpt, llm, it-) ищем только как отдельное слово:
    подстрочный поиск «ии» ловил «опции», «версии», «информации» и тащил
    в дайджест посторонние новости."""
    needle = keyword.strip()
    if not needle:
        return False
    if len(needle) <= 4 and " " not in needle:
        # ключ с дефисом на конце (it-) — префикс слова: справа буква допустима
        right = "" if needle.endswith("-") else r"(?![0-9a-zа-яё])"
        pattern = rf"(?<![0-9a-zа-яё]){re.escape(needle)}{right}"
        return re.search(pattern, haystack) is not None
    return needle in haystack


def matches_theme(item: dict, keyword_sets: list[list[str]]) -> bool:
    haystack = f"{item['title']} {item['description']}".lower()
    return any(any(keyword_hit(k, haystack) for k in ks) for ks in keyword_sets)


def collect(user: dict, max_items: int = 4) -> list[dict]:
    """Собирает до max_items свежих новостей по темам участника."""
    themes = (user.get("themes") or [])[:5]
    if not themes:
        return []
    keyword_sets = [theme_keywords(t) for t in themes]
    sent_titles = {s.split("|", 1)[1] if "|" in s else s
                   for s in (user.get("sent_titles") or [])}

    candidates: list[dict] = []
    for src, url in FEEDS.items():
        try:
            for item in fetch_feed(url):
                if not matches_theme(item, keyword_sets):
                    continue
                if item["title"] in sent_titles:
                    continue
                item["source"] = src
                candidates.append(item)
        except Exception:
            continue  # один упавший фид не валит дайджест

    chosen: list[dict] = []
    seen_titles: set[str] = set()
    for item in candidates:
        if item["title"] in seen_titles:
            continue
        seen_titles.add(item["title"])
        chosen.append(item)
        if len(chosen) >= max_items:
            break
    return chosen


def block_text(item: dict) -> str:
    note = item.get("description") or ""
    if len(note) > 160:
        note = note[:157].rstrip() + "…"
    lines = [f"**{item['title']}**"]
    if note:
        lines.append(note)
    lines.append(f"[читать]({item['link']})")
    return "\n".join(lines)


def assemble(items: list[dict], user: dict) -> str:
    now = datetime.datetime.now()
    themes_label = ", ".join(user.get("themes") or [])
    header = f"**Новости** · {themes_label} · {now:%d.%m %H:%M}\n"
    blocks = [f"▪️ {block_text(i)}" for i in items]
    text = header + "\n\n" + "\n\n".join(blocks)
    if len(text) > 4000:
        # резервируем блок: укорачиваем самые длинные описания
        while len(text) > 4000 and items:
            longest = max(range(len(items)), key=lambda k: len(items[k].get("description") or ""))
            items[longest]["description"] = ""
            blocks = [f"▪️ {block_text(i)}" for i in items]
            text = header + "\n\n" + "\n\n".join(blocks)
        if len(text) > 4000:
            blocks = blocks[: max(1, len(blocks) - 1)]
            text = header + "\n\n" + "\n\n".join(blocks)
    return text
