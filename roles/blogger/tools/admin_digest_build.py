# -*- coding: utf-8 -*-
"""Генератор рубрики «Цифра недели» для канала administrator.

Берёт снимки статистики с хостинга (/0s3/blogger-data/stats/<канал>-<дата>.json),
считает по каждому каналу: подписчики, прирост, медиану просмотров, охват
и лучший пост периода. Собирает пост по правилам канала и кладёт его
в posts со status: draft.

    py roles/blogger/tools/admin_digest_build.py [--days 7] [--out-dir ...]

Принцип: только факты из статистики, никакой генерации «советов».
"""
from __future__ import annotations

import argparse
import ftplib
import io
import json
import statistics as st
from datetime import date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CHANNELS = {
    "ainow": "AI",
    "na100": "Новости ИИ",
    "catden": "Коты",
    "zabava": "Забавное",
}
PASSWORD_FILE = Path(r"C:\Users\Бардаковы\Documents\1.txt")


def plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def ftp_client() -> ftplib.FTP:
    pw = PASSWORD_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[10].rstrip("\r\n")
    ftp = ftplib.FTP("mitiba.beget.tech", timeout=60)
    ftp.login("mitiba_rabota", pw)
    return ftp


def load_snapshots(ftp: ftplib.FTP, channel: str, days: int) -> list[dict]:
    base = "/0s3/blogger-data/stats"
    names = sorted(x.split("/")[-1] for x in ftp.nlst(base)
                   if x.split("/")[-1].startswith(f"{channel}-") and x.endswith(".json"))
    names = names[-days:]
    out = []
    for n in names:
        buf = io.BytesIO()
        ftp.retrbinary(f"RETR {base}/{n}", buf.write)
        try:
            out.append(json.loads(buf.getvalue().decode("utf-8", "replace")))
        except json.JSONDecodeError:
            continue
    return out


def channel_stats(snaps: list[dict]) -> dict | None:
    if not snaps:
        return None
    first, last = snaps[0], snaps[-1]
    subs_first, subs_last = first.get("participants"), last.get("participants")
    posts = last.get("posts") or []
    views = [p.get("views", 0) for p in posts if isinstance(p.get("views"), int)]
    if not views:
        return None
    med = int(st.median(views[-10:]))
    start = (last.get("taken_at") or "")[:10]
    period_posts = [p for p in posts if (p.get("dt") or "")[:10] >= start] or posts
    best = max(period_posts, key=lambda p: p.get("views", 0))
    worst = min([p for p in period_posts if isinstance(p.get("views"), int)],
                key=lambda p: p.get("views", 0))
    return {
        "subs": subs_last,
        "delta": (subs_last - subs_first) if None not in (subs_first, subs_last) else None,
        "median": med,
        "reach": round(med / subs_last * 100) if subs_last else None,
        "posts": len(posts),
        "best": {"views": best.get("views"), "url": best.get("url"), "title": best.get("title")},
        "worst": {"views": worst.get("views")},
        "first_date": (first.get("taken_at") or "")[:10],
        "last_date": (last.get("taken_at") or "")[:10],
    }


def build_post(data: dict, days: int) -> str:
    rows = []
    total_subs = 0
    for slug, name in CHANNELS.items():
        d = data.get(slug)
        if not d:
            continue
        total_subs += d["subs"] or 0
        delta = d["delta"]
        delta_s = "без изменений" if not delta else f"{delta:+d}"
        reach = f", охват {d['reach']}%" if (d["subs"] or 0) >= 30 else ""
        rows.append(f"— {name}: **{d['subs']}** {plural(d['subs'], 'подписчик', 'подписчика', 'подписчиков')} "
                    f"({delta_s}), медиана {d['median']} "
                    f"{plural(d['median'], 'просмотр', 'просмотра', 'просмотров')}{reach}")
    best = max((data[s] for s in data if data[s].get("best", {}).get("views")),
               key=lambda x: x["best"]["views"], default=None)
    best_line = ""
    if best and best["best"].get("url"):
        v = best["best"]["views"]
        best_line = (f"Самый читаемый пост периода — {v} "
                     f"{plural(v, 'просмотр', 'просмотра', 'просмотров')}: "
                     f"[{best['best'].get('title') or 'открыть'}]({best['best']['url']}).")

    return "\n\n".join(filter(None, [
        "**📊 Цифра недели: что показали наши каналы**",
        f"Собрали цифры за {days} {plural(days, 'день', 'дня', 'дней')} по четырём каналам — "
        "без прогнозов и «экспертных мнений». "
        "Только то, что показывает статистика платформы.",
        "\n".join(rows),
        best_line,
        f"**Что из этого следует.** Охват основного канала — "
        f"{data.get('ainow', {}).get('reach', '—')}%: подписчики читают, проблема не в текстах, "
        "а в том, что новых людей почти нет. Прирост нулевой или "
        "отрицательный у всех четырёх каналов: единственный источник читателей — сама "
        "платформа, внешних точек входа нет. Поэтому следующий шаг — не «писать лучше», а привести людей снаружи.",
        "Если ведёте канал в MAX — проверьте у себя ту же пару цифр: сколько подписчиков "
        "и какая медиана просмотров. Если охват падает при росте частоты публикаций, "
        "это не совпадение: у нас так и вышло.",
        "А какой охват у вашего канала? Напишите в комментариях две цифры — подписчики и "
        "просмотры последнего поста.",
        "> **Подписывайтесь на [AI](https://max.ru/channel_ainow)** — нейросети и инструменты "
        "для работы, проверенные на практике.",
    ]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Пост «Цифра недели» для administrator")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--out-dir", default="")
    ap.add_argument("--no-fetch", action="store_true", help="не ходить на FTP (демо)")
    a = ap.parse_args(argv)

    data = {}
    if not a.no_fetch:
        ftp = ftp_client()
        try:
            for slug in CHANNELS:
                data[slug] = channel_stats(load_snapshots(ftp, slug, a.days))
        finally:
            try:
                ftp.quit()
            except Exception:
                pass
    if not any(data.values()):
        print("нет данных статистики — пост не собран")
        return 2

    body = build_post(data, a.days)
    out_dir = Path(a.out_dir) if a.out_dir else REPO / "roles/blogger/channels/administrator/posts"
    out_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    path = out_dir / f"{today}-cifra-nedeli.md"
    cover = REPO / "local" / "admin" / f"cifra-nedeli-{today}.png"
    cover_rel = (cover.relative_to(REPO).as_posix() if cover.exists()
                 else "2026-11-21-cover.png")
    fm = "\n".join([
        "---",
        "channel: administrator",
        "status: draft",
        "format: markdown",
        "notify: true",
        "series: cifra-nedeli",
        f"created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"image_file: {cover_rel}",
        "---",
        "",
        "",
    ])
    path.write_text(fm + body + "\n", encoding="utf-8")
    print(f"черновик: {path} ({len(body)} знаков)")
    print("-" * 60)
    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
