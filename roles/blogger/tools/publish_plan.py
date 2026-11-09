# -*- coding: utf-8 -*-
"""Публикация следующего поста из плана Забавное с проверкой 4 часов.

Использование:
  python roles/blogger/tools/publish_plan.py [--plan local/zabava-plan.json]
                                             [--dry-run] [--status]

Логика запуска:
  * берётся первый пост со статусом pending;
  * через GET /messages?chat_id=..&count=1 определяется время последней
    публикации канала;
  * если прошло меньше interval_hours (по умолчанию 4) — публикация не
    выполняется, выводится ближайшее допустимое время (код 2);
  * если за сегодня (МСК) уже вышло daily_limit постов — выход (код 3);
  * иначе запускается roles/blogger/tools/publish_video.py, который сам
    делает проверку текста, загрузку медиа и GET-контроль;
  * при успехе в план дописываются статус, время и ссылка.
"""

import json
import re
import ssl
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(r"E:\github\MAX")
PLAN = REPO / "local" / "zabava-plan.json"
REPORT = REPO / "local" / "publish-plan.txt"
MSK = timezone(timedelta(hours=3))
TOKENS = REPO / "local" / "tokens.json"
CA = REPO / "local" / "russian_ca_bundle.pem"
PUBLISHER = REPO / "roles" / "blogger" / "tools" / "publish_video.py"
DELETER = REPO / "roles" / "blogger" / "tools" / "delete_post_by_slug.py"

REPORT_LINES = []


def say(line: str = "") -> None:
    REPORT_LINES.append(line)
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"))


def flush() -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(REPORT_LINES) + "\n", encoding="utf-8")


def load_tokens() -> dict:
    return json.loads(TOKENS.read_text(encoding="utf-8"))


def api(token: str, path: str) -> dict:
    ctx = ssl.create_default_context()
    if CA.exists():
        ctx.load_verify_locations(cafile=str(CA))
    req = urllib.request.Request("https://platform-api2.max.ru" + path,
                                 headers={"Authorization": token,
                                          "User-Agent": "curl/8.13.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def ts_msk(value: float) -> str:
    return datetime.fromtimestamp(value / 1000, MSK).strftime("%Y-%m-%d %H:%M:%S MSK")


def day_bounds(now: datetime) -> tuple[float, float]:
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.timestamp() * 1000, (start + timedelta(days=1)).timestamp() * 1000


def read_front_matter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}
    data = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith(" "):
            key, value = line.split(":", 1)
            data[key.strip()] = value.strip()
    return data


def main() -> None:
    args = sys.argv[1:]
    plan_path = PLAN
    if "--plan" in args:
        i = args.index("--plan")
        plan_path = Path(args[i + 1])
        if not plan_path.is_absolute():
            plan_path = REPO / plan_path
        del args[i:i + 2]
    dry_run = "--dry-run" in args
    if dry_run:
        args.remove("--dry-run")
    status_only = "--status" in args
    if status_only:
        args.remove("--status")
    if args:
        raise SystemExit("Использование: publish_plan.py [--plan файл] [--dry-run] [--status]")

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    channel = plan.get("channel") or "zabava"
    interval = float(plan.get("interval_hours") or 4)
    daily_limit = int(plan.get("daily_limit") or 3)
    posts = plan.get("posts") or []

    say(f"план: {plan_path.name}, канал: {channel}")
    say(f"интервал: {interval:g} ч, дневной лимит: {daily_limit}")
    for item in posts:
        mark = {"pending": " ", "published": "x", "skipped": "-"}.get(item.get("status"), "?")
        extra = ""
        if item.get("url"):
            extra = " " + item["url"]
        say(f"  [{mark}] {item.get('id')}. {Path(item.get('file', '')).name} "
            f"({item.get('status')}){extra}")

    if status_only:
        flush()
        return

    pending = next((p for p in posts if p.get("status") == "pending"), None)
    if not pending:
        say("все посты плана опубликованы — новых задач нет")
        flush()
        return

    entry = load_tokens()[channel]
    token = entry["token"]
    chat_id = int(entry["chat_id"])

    now = datetime.now(MSK)
    last = (api(token, f"/messages?chat_id={chat_id}&count=1").get("messages") or [None])[0]
    if not last:
        raise SystemExit("не удалось получить последнюю публикацию канала")
    last_ms = float(last.get("timestamp", 0))
    allowed_at = datetime.fromtimestamp(last_ms / 1000, MSK) + timedelta(hours=interval)

    say("")
    say(f"последняя публикация: {ts_msk(last_ms)}")
    say(f"сейчас:              {now.strftime('%Y-%m-%d %H:%M:%S MSK')}")
    say(f"следующий пост:      {Path(pending['file']).name}")
    say(f"ближайшее время:     {allowed_at.strftime('%Y-%m-%d %H:%M:%S MSK')}")

    if now < allowed_at:
        wait = allowed_at - now
        hours, rem = divmod(int(wait.total_seconds()), 3600)
        minutes = rem // 60
        say(f"РАНО: прошло меньше {interval:g} ч, ждать {hours} ч {minutes} мин")
        flush()
        sys.exit(2)

    start, end = day_bounds(now)
    today = api(token, f"/messages?chat_id={chat_id}&count=50").get("messages") or []
    today_count = sum(1 for m in today if start <= float(m.get("timestamp", 0)) < end)
    say(f"постов за сегодня: {today_count} из {daily_limit}")
    if today_count >= daily_limit:
        say(f"ЛИМИТ: {today_count} постов за сегодня, следующий — завтра")
        flush()
        sys.exit(3)

    post_path = REPO / pending["file"]
    if not post_path.exists():
        raise SystemExit(f"файл поста не найден: {post_path}")
    fm = read_front_matter(post_path)
    if fm.get("status") == "published":
        say("ВНИМАНИЕ: пост уже published, помечаю в плане и завершаюсь")
        pending["status"] = "published"
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
        flush()
        sys.exit(4)

    cmd = [sys.executable, str(PUBLISHER), "--channel", channel]
    if dry_run:
        cmd.append("--dry-run")
    cmd.append(str(post_path))
    say("")
    say("запуск: " + " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True,
                            encoding="utf-8", errors="replace")

    publisher_report = REPO / "local" / f"publish-{channel}-video.txt"
    if publisher_report.exists():
        say("")
        say("--- отчёт публикатора ---")
        for line in publisher_report.read_text(encoding="utf-8").splitlines():
            say(line)

    if result.returncode != 0:
        say("")
        say(f"FAIL: публикатор завершился с кодом {result.returncode}")
        if result.stderr.strip():
            say(result.stderr.strip()[-1500:])
        flush()
        sys.exit(result.returncode or 1)

    if dry_run:
        say("")
        say("DRY-RUN: публикация не выполнялась, план не изменён")
        flush()
        return

    fm = read_front_matter(post_path)
    pending["status"] = "published"
    pending["published_at"] = fm.get("published_at") or now.strftime("%Y-%m-%dT%H:%M:%S+03:00")
    if fm.get("url"):
        pending["url"] = fm["url"]
    if fm.get("message_id"):
        pending["message_id"] = fm["message_id"]

    source = pending.get("source")
    if source and pending.get("delete_source", True):
        slug = source.rstrip("/").split("/")[-1]
        say("")
        say(f"удаление исходного поста: {slug}")
        del_cmd = [sys.executable, str(DELETER), "--channel", channel, slug]
        del_result = subprocess.run(del_cmd, cwd=str(REPO), capture_output=True, text=True,
                                    encoding="utf-8", errors="replace")
        if del_result.stdout.strip():
            say(del_result.stdout.strip())
        if del_result.returncode == 0:
            pending["source_deleted"] = True
            pending["source_deleted_at"] = datetime.now(MSK).strftime("%Y-%m-%dT%H:%M:%S+03:00")
        else:
            pending["source_deleted"] = False
            pending["source_delete_error"] = (del_result.stdout.strip()
                                               or del_result.stderr.strip())[-500:]
            say(f"ВНИМАНИЕ: исходный пост не удалён (код {del_result.returncode})")

    plan["updated_at"] = now.strftime("%Y-%m-%dT%H:%M:%S+03:00")
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    left = sum(1 for p in posts if p.get("status") == "pending")
    say("")
    say(f"ГОТОВО: пост {pending['id']} опубликован"
        + (f" -> {pending['url']}" if pending.get("url") else ""))
    say(f"осталось в плане: {left}")
    flush()


if __name__ == "__main__":
    main()
