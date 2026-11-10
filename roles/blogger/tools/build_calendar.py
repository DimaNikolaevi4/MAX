#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Календарь блогера: что опубликовано, что запланировано, что удалено.

Использование:
  python roles/blogger/tools/build_calendar.py [--days 30] [--push] [--out <файл>]

Источники данных:
  * front matter постов `roles/blogger/channels/<slug>/posts/*.md`
    (status, published_at, url, views, deleted_at);
  * план «Забавного» `local/zabava-plan.json` (pending — запланировано);
  * реестр каналов `roles/blogger/config/channels.json` (каналы под удаление).

Результат — `docs/blogger-calendar.md`. С `--push` скрипт коммитит и пушит
календарь, как остальные задачи Планировщика Windows (задача «MAX blogger
calendar», ежедневно 07:20 МСК).

Дата поста: `published_at`, иначе префикс YYYY-MM-DD в имени файла.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from shared.paths import CHANNELS, CONFIG, LOCAL  # noqa: E402

MSK = timezone(timedelta(hours=3))
OUT = REPO / "docs" / "blogger-calendar.md"
PLAN = LOCAL / "zabava-plan.json"
DAYS = 30

WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
STATUS_RU = {
    "published": "опубликован",
    "approved": "к публикации",
    "draft": "черновик",
    "deleted": "удалён",
    "pending": "в плане",
}

LINES: list[str] = []


def say(line: str = "") -> None:
    LINES.append(line)
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"))


# ---------------------------------------------------------------- разбор постов
def read_front_matter(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n?", text, re.S)
    if not m:
        return {}, text
    fm: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "\t", "-")):
            key, value = line.split(":", 1)
            fm[key.strip()] = value.strip()
    return fm, text[m.end():]


def post_title(body: str, path: Path) -> str:
    for line in body.splitlines():
        s = line.strip()
        if not s:
            continue
        s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
        s = re.sub(r"[*_`>#]+", "", s).strip(" —-•")
        if s:
            return s[:80] + ("…" if len(s) > 80 else "")
    return path.stem


def post_date(fm: dict[str, str], path: Path) -> date | None:
    raw = (fm.get("published_at") or "").strip()
    if raw and raw.lower() not in ("null", "none", "~", ""):
        m = re.match(r"(\d{4}-\d{2}-\d{2})", raw)
        if m:
            return date.fromisoformat(m.group(1))
    m = re.match(r"(\d{4}-\d{2}-\d{2})", path.name)
    return date.fromisoformat(m.group(1)) if m else None


def as_int(value: str | None) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def collect_posts() -> tuple[list[dict], list[dict]]:
    """Посты всех каналов и записи реестра каналов."""
    cfg = json.loads((CONFIG / "channels.json").read_text(encoding="utf-8"))
    channels = cfg["channels"]
    posts: list[dict] = []
    for ch in channels:
        slug = ch["slug"]
        posts_dir = CHANNELS / slug / "posts"
        if not posts_dir.exists():
            continue
        for path in sorted(posts_dir.glob("*.md")):
            fm, body = read_front_matter(path)
            status = (fm.get("status") or "draft").strip().lower()
            deleted_at = (fm.get("deleted_at") or "").strip()
            if deleted_at and status != "deleted":
                status = "deleted"
            posts.append(
                {
                    "channel": slug,
                    "path": path,
                    "file": path.name,
                    "title": post_title(body, path),
                    "status": status,
                    "date": post_date(fm, path),
                    "published_at": (fm.get("published_at") or "").strip(),
                    "deleted_at": deleted_at,
                    "url": (fm.get("url") or "").strip(),
                    "views": as_int(fm.get("views")),
                    "hold": (fm.get("hold") or "").strip(),
                }
            )
    return posts, channels


def collect_plan(channels: list[dict]) -> list[dict]:
    """pending-посты плана «Забавного» — то, что выйдет в ближайшие дни."""
    if not PLAN.exists():
        return []
    try:
        data = json.loads(PLAN.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    items: list[dict] = []
    for item in data.get("posts", []):
        if (item.get("status") or "").lower() != "pending":
            continue
        rel = item.get("file") or ""
        path = REPO / rel
        title = item.get("title") or ""
        if path.exists():
            fm, body = read_front_matter(path)
            title = title or post_title(body, path)
        items.append(
            {
                "id": item.get("id"),
                "title": title or f"пост #{item.get('id')}",
                "media": item.get("media") or "",
                "file": rel,
            }
        )
    return items


# ------------------------------------------------------------------ отрисовка
def cell(text: str) -> str:
    return (text or "—").replace("|", "\\|").replace("\n", " ").strip()


def table(headers: list[str], rows: list[list[str]]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join([" --- "] * len(headers)) + "|"]
    for row in rows:
        out.append("| " + " | ".join(cell(c) for c in row) + " |")
    return out


def link(url: str) -> str:
    return f"[открыть]({url})" if url else "—"


def render(posts: list[dict], channels: list[dict], plan: list[dict], days: int) -> str:
    now = datetime.now(MSK)
    today = now.date()
    since = today - timedelta(days=days - 1)
    by_slug = {c["slug"]: c for c in channels}
    title_of = {c["slug"]: c.get("title") or c["slug"] for c in channels}

    published = [p for p in posts if p["status"] == "published" and p["date"]]
    upcoming = [p for p in posts if p["status"] == "approved"]
    drafts = [p for p in posts if p["status"] == "draft"]
    deleted = [p for p in posts if p["status"] == "deleted"]

    out: list[str] = []
    out.append("# Календарь блогера")
    out.append("")
    out.append("> Файл собирается автоматически: Планировщик Windows, задача "
               "«MAX blogger calendar», ежедневно в 07:20 МСК.")
    out.append("> Ручные правки бессмысленны — при следующем запуске файл перезаписывается. "
               "Источники: front matter постов `roles/blogger/channels/*/posts/`, план "
               "«Забавного» `local/zabava-plan.json`, реестр `roles/blogger/config/channels.json`.")
    out.append("")
    out.append(f"Обновлено: **{now:%d.%m.%Y %H:%M} МСК** · горизонт: последние {days} дней "
               f"и всё запланированное")
    out.append("")

    # --- сводка
    window = [p for p in published if p["date"] and since <= p["date"] <= today]
    counter = Counter(p["channel"] for p in window)
    summary = ", ".join(f"{title_of.get(k, k)} — {v}" for k, v in counter.most_common()) or "нет публикаций"
    out.append("## Сводка")
    out.append("")
    out.append(f"- Опубликовано за {days} дней: **{len(window)}** ({summary})")
    out.append(f"- К публикации: **{len(upcoming)}** (со статусом `approved`)"
               + (f" · в плане «Забавного» ждут слота: **{len(plan)}**" if plan else ""))
    to_delete = [c for c in channels if c.get("status") == "to_delete"]
    out.append(f"- Черновики: **{len(drafts)}** · удалено постов: **{len(deleted)}** · каналов под удаление: **{len(to_delete)}**")
    out.append("")

    # --- состояние каналов
    out.append("## Каналы")
    out.append("")
    rows = []
    for ch in channels:
        slug = ch["slug"]
        state = "под удаление" if ch.get("status") == "to_delete" else "активен"
        rows.append([
            f"{ch.get('title') or slug} (`{slug}`)",
            (ch.get("platform") or "").upper(),
            state,
            ch.get("delete_on") or "—",
            str(sum(1 for p in window if p["channel"] == slug)),
        ])
    out.extend(table(["канал", "площадка", "состояние", "удаление", f"постов за {days} дн."], rows))
    out.append("")

    # --- сегодня
    out.append(f"## Сегодня — {today:%d.%m.%Y} ({WEEKDAYS[today.weekday()]})")
    out.append("")
    todays = [p for p in published if p["date"] == today]
    todays += [p for p in posts if p["status"] == "deleted" and p["deleted_at"][:10] == today.isoformat()]
    todays.sort(key=lambda x: x["published_at"] or x["deleted_at"], reverse=True)
    if todays:
        rows = [[title_of.get(p["channel"], p["channel"]), p["title"],
                 STATUS_RU.get(p["status"], p["status"]),
                 p["published_at"][11:16] if len(p["published_at"]) > 15 else "—",
                 link(p["url"])] for p in todays]
        out.extend(table(["канал", "пост", "статус", "время", "ссылка"], rows))
    else:
        out.append("Пока пусто — сегодня ещё ничего не вышло.")
    for item in plan[:1]:
        out.append("")
        out.append(f"Следующий из плана «Забавного»: **{item['title']}**"
                   + (f" ({item['media']})" if item["media"] else ""))
    out.append("")

    # --- запланировано
    out.append("## Запланировано")
    out.append("")
    rows = []
    for p in sorted(upcoming, key=lambda x: (x["date"] or date.max, x["file"])):
        when = p["date"].strftime("%d.%m.%Y") if p["date"] else "дата не указана"
        rows.append([when, title_of.get(p["channel"], p["channel"]), p["title"],
                     STATUS_RU.get(p["status"], p["status"]), link(p["url"])])
    for item in plan:
        rows.append(["ближайший слот 07:16", "Забавное (`zabava`)", item["title"],
                     STATUS_RU["pending"], "—"])
    if rows:
        out.extend(table(["когда", "канал", "пост", "статус", "ссылка"], rows))
    else:
        out.append("Ничего не запланировано.")
    out.append("")

    # --- история
    out.append(f"## Публикации за {days} дней (без сегодняшних)")
    out.append("")
    history = sorted((p for p in window if p["date"] != today),
                     key=lambda x: (x["date"], x["published_at"]), reverse=True)
    if history:
        rows = []
        for p in history:
            rows.append([
                p["date"].strftime("%d.%m"),
                title_of.get(p["channel"], p["channel"]),
                p["title"],
                str(p["views"]) if p["views"] is not None else "—",
                link(p["url"]),
            ])
        out.extend(table(["дата", "канал", "пост", "просмотры", "ссылка"], rows))
    else:
        out.append("За этот период публикаций нет.")
    out.append("")

    # --- удаления
    out.append("## Удалено")
    out.append("")
    rows = []
    for p in sorted(deleted, key=lambda x: x["deleted_at"], reverse=True):
        raw_when = p["deleted_at"][:10]
        try:
            when = date.fromisoformat(raw_when).strftime("%d.%m.%Y") if raw_when else "—"
        except ValueError:
            when = raw_when or "—"
        if not raw_when and p["date"]:
            when = p["date"].strftime("%d.%m.%Y")
        rows.append([when, title_of.get(p["channel"], p["channel"]), p["title"], link(p["url"])])
    for ch in channels:
        if ch.get("status") == "to_delete" and ch.get("delete_on"):
            try:
                day = date.fromisoformat(ch["delete_on"]).strftime("%d.%m.%Y")
            except ValueError:
                day = ch["delete_on"]
            rows.append([day, ch.get("title") or ch["slug"], "удаление канала целиком", "—"])
    if rows:
        out.extend(table(["дата", "канал", "что", "ссылка"], rows))
    else:
        out.append("Удалений не зафиксировано.")
    out.append("")
    out.append("> Удаления до 10.11.2026 в постах не отмечались (в календаре их нет). "
               "Новые удаления фиксирует `delete_post_by_slug.py`: ставит `status: deleted` "
               "и `deleted_at` в файл поста.")
    out.append("")
    out.append("## Черновики")
    out.append("")
    if drafts:
        rows = [[title_of.get(p["channel"], p["channel"]), p["title"],
                 p["date"].strftime("%d.%m.%Y") if p["date"] else "—",
                 p["hold"] or "—"] for p in drafts]
        out.extend(table(["канал", "пост", "дата в имени", "пауза"], rows))
    else:
        out.append("Черновиков нет.")
    out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------------- git
def git(*args: str):
    return subprocess.run(["git", *args], cwd=str(REPO), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def commit_and_push(path: Path) -> int:
    rel = path.relative_to(REPO).as_posix()
    git("add", rel)
    status = git("status", "--porcelain", "--", rel)
    if not status.stdout.strip():
        say("календарь без изменений — коммит не нужен")
        return 0

    git("fetch", "origin", "--quiet")
    behind = git("rev-list", "--count", f"HEAD..origin/main")
    if behind.returncode == 0 and behind.stdout.strip() not in ("", "0"):
        pull = git("pull", "--rebase", "--quiet", "origin", "main")
        if pull.returncode != 0:
            say("WARN: git pull --rebase не выполнен, пуш отложен")
            return 0

    msg = f"docs: календарь блогера обновлён {datetime.now(MSK):%Y-%m-%d %H:%M}"
    commit = git("commit", "-m", msg, "--", rel)
    if commit.returncode != 0:
        say("WARN: git commit не выполнен")
        say((commit.stdout or commit.stderr or "").strip()[-400:])
        return 0
    push = git("push", "origin", "main")
    if push.returncode != 0:
        say("WARN: git push не выполнен, коммит остался локально")
        say((push.stderr or "").strip()[-400:])
        return 0
    say(f"календарь закоммичен и отправлен: {rel}")
    return 0


def main() -> None:
    args = sys.argv[1:]
    days = DAYS
    if "--days" in args:
        i = args.index("--days")
        days = int(args[i + 1])
        del args[i:i + 2]
    out_path = OUT
    if "--out" in args:
        i = args.index("--out")
        out_path = Path(args[i + 1])
        if not out_path.is_absolute():
            out_path = REPO / out_path
        del args[i:i + 2]
    push = "--push" in args

    posts, channels = collect_posts()
    plan = collect_plan(channels)
    text = render(posts, channels, plan, days)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text + "\n", encoding="utf-8", newline="\n")
    say(f"календарь собран: {out_path.relative_to(REPO).as_posix()} "
        f"(постов {len(posts)}, в плане {len(plan)}, горизонт {days} дн.)")
    if push:
        commit_and_push(out_path)


if __name__ == "__main__":
    main()
