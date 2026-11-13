# -*- coding: utf-8 -*-
"""Публикация следующего поста из плана «Забавное» — без интервалов и лимитов.

Использование:
  python roles/blogger/tools/publish_plan.py [--plan local/zabava-plan.json]
                                             [--dry-run] [--status]

Логика запуска:
  * берётся первый пост со статусом pending;
  * никаких проверок интервала и дневного лимита нет: если пост pending —
    он публикуется;
  * запускается roles/blogger/tools/publish_video.py, который сам делает
    проверку текста, загрузку медиа, POST и GET-контроль;
  * при успехе в план дописываются статус, время и ссылка;
  * если контроль дал ошибку, но пост уже опубликован (front matter
    status: published) — план всё равно помечается, чтобы не было дубля.

Обёртка Планировщика (zabava_publish.ps1) запускает скрипт один раз за
утренний запуск — один pending за день. Правило 13.11.2026 (владелец): план
можно заполнять на несколько дней вперёд, очередь расходуется по одному
посту в день; zabava_random_plan.py при наличии pending ничего не добавляет.
"""

import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(r"E:\github\MAX")
PLAN = REPO / "local" / "zabava-plan.json"
REPORT = REPO / "local" / "publish-plan.txt"
MSK = timezone(timedelta(hours=3))
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


def git(*args):
    return subprocess.run(["git", *args], cwd=str(REPO), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def commit_published(post_path: Path) -> None:
    """Коммит опубликованного поста и реестра CTA. Медиа в git не попадают:
    они лежат в local/ (gitignore), а в .md остаётся ссылка на CDN."""
    files = [str(post_path.relative_to(REPO)).replace("\\", "/"),
             "roles/blogger/channels/zabava/cta-phrases.json"]
    git("add", *files)
    msg = f"roles/zabava: publish {post_path.stem} (plan)"
    commit = git("commit", "-m", msg, "--", *files)
    if commit.returncode != 0:
        say("ВНИМАНИЕ: git commit не выполнен")
        say((commit.stderr or commit.stdout or "").strip()[-500:])
        return
    say(f"коммит: {git('rev-parse', '--short', 'HEAD').stdout.strip()}")
    push = git("push", "origin", "main")
    if push.returncode != 0:
        say("ВНИМАНИЕ: git push не выполнен, коммит остался локально")
        say((push.stderr or "").strip()[-500:])


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
    posts = plan.get("posts") or []

    say(f"план: {plan_path.name}, канал: {channel}")
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

    now = datetime.now(MSK)
    say("")
    say(f"сейчас:         {now.strftime('%Y-%m-%d %H:%M:%S MSK')}")
    say(f"следующий пост: {Path(pending['file']).name}")

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
        fm_now = read_front_matter(post_path)
        if fm_now.get("status") == "published" and fm_now.get("message_id"):
            say("")
            say("ВНИМАНИЕ: публикатор вернул ошибку контроля, но пост уже опубликован.")
            say(f"  {fm_now.get('url', '')}")
            say("Помечаю в плане как published, чтобы не публиковать повторно.")
        else:
            say("")
            say(f"FAIL: публикатор завершился с кодом {result.returncode}")
            if result.stderr.strip():
                say(result.stderr.strip()[-1500:])
            pending["status"] = "skipped"
            pending["skip_reason"] = (result.stderr.strip()
                                      or result.stdout.strip())[-300:]
            plan["updated_at"] = now.strftime("%Y-%m-%dT%H:%M:%S+03:00")
            plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
            say("Пост помечен в плане как skipped — в следующий запуск "
                "zabava_random_plan.py выберет другой случайный пост.")
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

    say("")
    commit_published(post_path)

    left = sum(1 for p in posts if p.get("status") == "pending")
    say("")
    say(f"ГОТОВО: пост {pending['id']} опубликован"
        + (f" -> {pending['url']}" if pending.get("url") else ""))
    say(f"осталось в плане: {left}")
    flush()


if __name__ == "__main__":
    main()
