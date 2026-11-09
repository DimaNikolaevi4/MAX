# -*- coding: utf-8 -*-
"""Снимок и анализ статистики канала MAX (по умолчанию ainow).

Что делает:
  * GET /chats/{chat_id} — подписчики, число сообщений;
  * GET /messages?chat_id=...&count=100 — просмотры каждого поста (stat.views);
  * сохраняет снимок `local/stats/<канал>-<дата>.json` (один на день);
  * сравнивает с предыдущим снимком: прирост подписчиков, новые посты,
    прирост просмотров и скорость просмотров;
  * пишет отчёт `local/stats-report.txt`.

Запуск:
  py roles\\blogger\\tools\\stats_snapshot.py [--channel ainow] [--weekly]

`--weekly` собирает сводку за 7 дней в `local/stats-weekly.txt`.
"""
import argparse
import json
import ssl
import statistics
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
MSK = timezone(timedelta(hours=3))
STATS = REPO / "local" / "stats"
REPORT = REPO / "local" / "stats-report.txt"
WEEKLY = REPO / "local" / "stats-weekly.txt"
CA = REPO / "local" / "russian_ca_bundle.pem"
TOKENS = REPO / "local" / "tokens.json"


def api(token, path):
    ctx = ssl.create_default_context()
    if CA.exists():
        ctx.load_verify_locations(cafile=str(CA))
    req = urllib.request.Request(
        "https://platform-api2.max.ru" + path,
        headers={"Authorization": token, "User-Agent": "curl/8.13.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def load_snapshots(channel):
    out = []
    for p in sorted(STATS.glob(f"{channel}-*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def title_of(text):
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="ainow")
    ap.add_argument("--weekly", action="store_true")
    args = ap.parse_args()

    now = datetime.now(MSK)
    tokens = json.loads(TOKENS.read_text(encoding="utf-8"))
    entry = tokens[args.channel]
    chat_id = int(entry["chat_id"])

    chat = api(entry["token"], f"/chats/{chat_id}")
    c = chat.get("chat", chat)
    msgs = api(entry["token"], f"/messages?chat_id={chat_id}&count=100").get("messages", [])

    posts = []
    for m in msgs:
        body = m.get("body", {}) or {}
        ts = m.get("timestamp", 0)
        dt = datetime.fromtimestamp(ts / 1000, MSK) if ts else None
        posts.append({
            "mid": body.get("mid", ""),
            "dt": dt.isoformat() if dt else "",
            "views": (m.get("stat", {}) or {}).get("views"),
            "len": len(body.get("text", "") or ""),
            "attachments": [a.get("type") for a in (body.get("attachments") or [])],
            "url": m.get("url", ""),
            "title": title_of(body.get("text", "")),
        })
    posts.sort(key=lambda p: p["dt"])

    snap = {
        "taken_at": now.isoformat(),
        "channel": args.channel,
        "title": c.get("title"),
        "status": c.get("status"),
        "participants": c.get("participants_count"),
        "messages_count": c.get("messages_count"),
        "posts": posts,
    }
    STATS.mkdir(parents=True, exist_ok=True)
    snap_path = STATS / f"{args.channel}-{now:%Y-%m-%d}.json"
    snap_path.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [f"снимок: {now:%Y-%m-%d %H:%M} MSK, канал: {snap['title']} ({args.channel})",
             f"подписчиков: {snap['participants']}, сообщений: {snap['messages_count']}"]

    prev_snaps = [s for s in load_snapshots(args.channel)
                  if s.get("taken_at", "")[:10] < now.strftime("%Y-%m-%d")]
    prev = prev_snaps[-1] if prev_snaps else None
    if prev:
        prev_at = datetime.fromisoformat(prev["taken_at"])
        hours = max((now - prev_at).total_seconds() / 3600, 0.1)
        dp = (snap["participants"] or 0) - (prev.get("participants") or 0)
        lines.append(f"предыдущий снимок: {prev_at:%Y-%m-%d %H:%M}, "
                     f"подписчики: {dp:+d} за {hours:.1f} ч")

        prev_posts = {p["mid"]: p for p in prev.get("posts", [])}
        new_posts = [p for p in posts if p["mid"] not in prev_posts]
        if new_posts:
            lines.append("")
            lines.append("новые посты с прошлого снимка:")
            for p in new_posts:
                lines.append(f"  {p['views'] if p['views'] is not None else '-'} просм.  "
                             f"{p['title'][:70]}")

        gains = []
        for p in posts:
            old = prev_posts.get(p["mid"])
            if old is None or not isinstance(p["views"], int) or not isinstance(old.get("views"), int):
                continue
            delta = p["views"] - old["views"]
            gains.append((delta, p))
        gains.sort(key=lambda x: -x[0])
        if gains:
            lines.append("")
            lines.append("прирост просмотров (топ-5):")
            for delta, p in gains[:5]:
                lines.append(f"  +{delta:<4} {p['views']:>4}  "
                             f"{p['dt'][:10]}  {p['title'][:60]}")
    else:
        lines.append("предыдущих снимков нет — это база для будущей динамики")

    views = [p["views"] for p in posts if isinstance(p["views"], int)]
    if views:
        lines.append("")
        lines.append(f"просмотры (накопленные): min={min(views)}, "
                     f"median={int(statistics.median(views))}, max={max(views)}")
    lines.append(f"снимок сохранён: {snap_path.relative_to(REPO)}")

    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log = REPO / "local" / "logs" / "stats.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n\n")

    if args.weekly:
        write_weekly(args.channel)
    print("ok")
    return 0


def write_weekly(channel):
    snaps = load_snapshots(channel)
    now = datetime.now(MSK)
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    snaps = [s for s in snaps if s.get("taken_at", "")[:10] >= week_ago]
    if len(snaps) < 2:
        lines = ["недостаточно снимков за неделю (нужно минимум 2)"]
    else:
        first, last = snaps[0], snaps[-1]
        lines = [f"недельная сводка {channel}: {first['taken_at'][:10]} .. "
                 f"{last['taken_at'][:10]}",
                 f"подписчики: {first.get('participants')} -> {last.get('participants')} "
                 f"({(last.get('participants') or 0) - (first.get('participants') or 0):+d})"]
        old = {p["mid"]: p for p in first.get("posts", [])}
        gains = []
        for p in last.get("posts", []):
            o = old.get(p["mid"])
            if o and isinstance(p.get("views"), int) and isinstance(o.get("views"), int):
                gains.append((p["views"] - o["views"], p))
        gains.sort(key=lambda x: -x[0])
        lines.append("")
        lines.append("топ-10 по приросту просмотров за неделю:")
        for delta, p in gains[:10]:
            lines.append(f"  +{delta:<4} {p['views']:>4}  {p['dt'][:10]}  {p['title'][:60]}")
        new_posts = [p for p in last.get("posts", []) if p["mid"] not in old]
        lines.append("")
        lines.append(f"новых постов за неделю: {len(new_posts)}")
    WEEKLY.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
