#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Экспорт плана MAX для глобального календаря (E:\\github\\Календарь).

Пишет `plan.json` в корне MAX — источник истины для drop.py в хаб.
Источники те же, что у build_calendar.py:
  * посты каналов (front matter): approved → scheduled (дата = published_at
    или префикс имени файла), draft → backlog, published за 30 дней → done,
    deleted → пропускается;
  * local/zabava-plan.json: pending → scheduled на завтра 07:16,
    published за 30 дней → done;
  * channels.json: статус to_delete → todo на дату delete_on.

Запуск: py roles\\blogger\\tools\\export_plan.py
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from shared.paths import CHANNELS, CONFIG, LOCAL  # noqa: E402

MSK = timezone(timedelta(hours=3))
OUT = REPO / "plan.json"
RECENT = 30


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


def body_title(body: str) -> str:
    for line in body.splitlines():
        s = line.strip()
        if not s:
            continue
        s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
        s = re.sub(r"[*_`>#]+", "", s).strip(" —-•")
        if s:
            return s[:80]
    return "без заголовка"


def post_date(fm: dict[str, str], path: Path) -> str:
    raw = (fm.get("published_at") or "").strip()
    if raw[:10]:
        return raw[:10]
    m = re.match(r"(\d{4}-\d{2}-\d{2})", path.name)
    return m.group(1) if m else ""


def main() -> None:
    now = datetime.now(MSK)
    today = now.date()
    horizon = today - timedelta(days=RECENT)

    cfg = json.loads((CONFIG / "channels.json").read_text(encoding="utf-8"))
    title_of = {c["slug"]: c.get("title") or c["slug"] for c in cfg["channels"]}

    tasks: list[dict] = []

    def add(task_id: str, title: str, when: str | None, status: str,
            why: str = "", link: str = "", source: str = "auto") -> None:
        tasks.append({"id": task_id, "title": title, "when": when,
                      "time": None, "status": status, "why": why,
                      "link": link, "source": source})

    # --- посты каналов ---
    for ch_dir in sorted(CHANNELS.iterdir()):
        if not (ch_dir / "posts").is_dir():
            continue
        for md in sorted((ch_dir / "posts").glob("*.md")):
            fm, body = read_front_matter(md)
            status = (fm.get("status") or "draft").strip().lower()
            if fm.get("deleted_at"):
                status = "deleted"
            if status == "deleted":
                continue
            channel = title_of.get(ch_dir.name, ch_dir.name)
            title = f"[{channel}] {body_title(body)}"
            tid = f"max-{md.stem}"
            link = str(md.relative_to(REPO)).replace("\\", "/")
            if status == "approved":
                add(tid, title, post_date(fm, md) or None, "scheduled",
                    f"публикация по Планировщику, канал «{channel}»", link)
            elif status == "draft":
                add(tid, title, None, "backlog", "черновик, ждёт «ок» владельца",
                    link)
            elif status == "published":
                d = post_date(fm, md)
                if d and date.fromisoformat(d) >= horizon:
                    add(tid, title, d, "done", "", link)

    # --- план «Забавного» ---
    plan_path = LOCAL / "zabava-plan.json"
    if plan_path.is_file():
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        for entry in plan.get("posts") or []:
            st = (entry.get("status") or "").lower()
            post = REPO / (entry.get("file") or "")
            title = body_title(post.read_text(encoding="utf-8", errors="replace")
                               .split("---", 2)[-1]) if post.is_file() \
                else (entry.get("media") or "пост плана")
            if st == "pending":
                when = (today + timedelta(days=1)).isoformat()
                add(f"max-plan-{entry.get('id')}", f"[Забавное] {title}",
                    when, "scheduled", "выход из плана в 07:16", str(entry.get("file") or ""))
            elif st == "published":
                raw = (entry.get("published_at") or "")[:10]
                if raw and date.fromisoformat(raw) >= horizon:
                    add(f"max-plan-{entry.get('id')}", f"[Забавное] {title}",
                        raw, "done", "", str(entry.get("file") or ""))

    # --- каналы под удаление ---
    for ch in cfg["channels"]:
        if ch.get("status") == "to_delete" and ch.get("delete_on"):
            add(f"max-delete-{ch['slug']}",
                f"Удаление канала «{ch.get('title') or ch['slug']}» целиком",
                ch["delete_on"], "todo", "решение владельца зафиксировано в реестре")

    tasks.sort(key=lambda t: (t.get("when") or "9999", t["id"]))
    out = {"tasks": tasks}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    counts = {}
    for t in tasks:
        counts[t["status"]] = counts.get(t["status"], 0) + 1
    print(f"plan.json: задач {len(tasks)} "
          f"({', '.join(f'{k}={v}' for k, v in sorted(counts.items()))})")


if __name__ == "__main__":
    main()
