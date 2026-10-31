# -*- coding: utf-8 -*-
"""Собирает мини-сайт и RSS-ленту для подключения канала Дзена.

    python tools/dzen_build.py [--channel ainow] [--base https://0s3.ru/dzen]

На выходе — папка dzen/:
  index.html      — список материалов
  <slug>.html     — страницы материалов (ЧПУ, без параметров)
  rss.xml         — лента RSS 2.0 по требованиям Дзена (content:encoded, enclosure)
"""
import argparse
import html
import re
from email.utils import format_datetime
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "dzen"
MSK = timezone(timedelta(hours=3))
LIMIT = 16
SKIP = {"2026-09-28-replit-github-kak-vydat-iiagentu-ne"}


def md_to_html(text: str) -> str:
    """Простое markdown → HTML в пределах того, что понимает Дзен."""
    def inline(s: str) -> str:
        s = html.escape(s, quote=False)
        s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<i>\1</i>", s)
        return s

    blocks = [b.strip() for b in re.split(r"\n\s*\n", text.strip()) if b.strip()]
    out = []
    for i, block in enumerate(blocks):
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if all(l.startswith("— ") or l.startswith("• ") for l in lines) and lines:
            items = "".join(f"<li>{inline(l[2:].strip())}</li>" for l in lines)
            out.append(f"<ul>{items}</ul>")
            continue
        if all(l.startswith("> ") for l in lines):
            out.append("<blockquote>" + "<br>".join(inline(l[2:]) for l in lines) + "</blockquote>")
            continue
        if len(lines) == 1 and i == 0:
            h = re.sub(r"\*\*", "", lines[0])
            h = re.sub(r"^[^\wА-Яа-яA-Za-z0-9«\"(]+", "", h).strip()
            out.append(f"<h1>{inline(h)}</h1>")
            continue
        if len(lines) == 1 and lines[0].startswith("**") and lines[0].endswith("**"):
            out.append(f"<h2>{inline(lines[0][2:-2])}</h2>")
            continue
        if len(lines) == 1 and len(lines[0]) < 70 and not lines[0].endswith((".", "!", "?")):
            out.append(f"<h2>{inline(lines[0])}</h2>")
            continue
        out.append("<p>" + "<br>".join(inline(l) for l in lines) + "</p>")
    return "\n".join(out)


def plain(text: str) -> str:
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    t = re.sub(r"[*_`>#]", "", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def read_post(p: Path):
    raw = p.read_text(encoding="utf-8")
    m = re.match(r"---\r?\n(.*?)\r?\n---\r?\n?(.*)", raw, re.S)
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    return fm, m.group(2).strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="ainow")
    ap.add_argument("--base", default="https://0s3.ru/dzen")
    ap.add_argument("--limit", type=int, default=LIMIT)
    a = ap.parse_args()

    posts = []
    for p in sorted((REPO / "channels" / a.channel / "posts").glob("*.md")):
        fm, body = read_post(p)
        if fm.get("status") != "published":
            continue
        if not fm.get("image"):
            continue  # без обложки материал в Дзене выглядит пусто
        if p.stem in SKIP:
            continue  # внутри промпта есть маска ******, ломающая разметку
        posts.append((fm.get("published_at", ""), p.stem, fm, body))
    posts.sort(reverse=True)
    posts = posts[: a.limit]

    OUT.mkdir(exist_ok=True)
    items_xml = []
    cards = []

    for pub, stem, fm, body in posts:
        slug = stem
        url = f"{a.base}/{slug}.html"
        title = plain(body.splitlines()[0])[:200]
        desc = plain(" ".join(body.splitlines()[1:4]))[:300]
        cover = fm.get("image") or fm.get("video_preview") or ""
        dt = datetime.fromisoformat(pub) if pub else datetime.now(MSK)
        content = md_to_html(body)
        img_html = f'<figure><img src="{cover}" alt="{html.escape(title)}"></figure>' if cover else ""
        page = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(desc)}">
<meta property="og:title" content="{html.escape(title)}">
<meta property="og:image" content="{html.escape(cover)}">
<link rel="alternate" type="application/rss+xml" href="{a.base}/rss.xml">
</head><body>
<article>
<p><a href="{a.base}/index.html">Нейро Мульт Студия</a> · <time datetime="{dt.isoformat()}">{dt.strftime('%d.%m.%Y')}</time></p>
{img_html}
{content}
</article>
</body></html>"""
        (OUT / f"{slug}.html").write_text(page, encoding="utf-8", newline="\n")

        cards.append(
            f'<li><a href="{a.base}/{slug}.html">{html.escape(title)}</a> '
            f'<time datetime="{dt.isoformat()}">{dt.strftime("%d.%m.%Y")}</time></li>'
        )
        items_xml.append(f"""  <item>
    <title>{html.escape(title)}</title>
    <link>{url}</link>
    <guid isPermaLink="true">{url}</guid>
    <pubDate>{format_datetime(dt)}</pubDate>
    <category>format-article</category>
    <category>index</category>
    <category>comment-all</category>
    <description>{html.escape(desc)}</description>
    {f'<enclosure url="{html.escape(cover)}" type="image/jpeg"/>' if cover else ''}
    <content:encoded><![CDATA[{img_html}{content}]]></content:encoded>
  </item>""")

    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel>
  <title>Нейро Мульт Студия</title>
  <link>{a.base}/</link>
  <description>Мультфильм с нейросетями: процесс, инструменты и разборы</description>
  <language>ru</language>
{chr(10).join(items_xml)}
</channel>
</rss>
"""
    (OUT / "rss.xml").write_text(feed, encoding="utf-8", newline="\n")

    index = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"><title>Нейро Мульт Студия</title>
<link rel="alternate" type="application/rss+xml" href="{a.base}/rss.xml">
</head><body>
<h1>Нейро Мульт Студия</h1>
<p>Мультфильм с нейросетями: процесс, инструменты и разборы.</p>
<ul>
{chr(10).join(cards)}
</ul>
</body></html>"""
    (OUT / "index.html").write_text(index, encoding="utf-8", newline="\n")

    print(f"материалов: {len(posts)}")
    print(f"фид: {OUT / 'rss.xml'} ({len(feed)} символов)")
    print(f"первая ссылка: {a.base}/{posts[0][1]}.html")


if __name__ == "__main__":
    main()
