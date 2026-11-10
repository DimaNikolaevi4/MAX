# -*- coding: utf-8 -*-
"""Публикация постов со `status: approved` по расписанию (Планировщик Windows).

Логика запуска:
  * берутся посты канала со `status: approved`, у которых дата из имени файла
    не позже сегодняшней (МСК);
  * за один запуск публикуются все готовые посты (`--limit 0` — без ограничения);
  * перед публикацией: `git fetch`, отказ, если origin/main ушёл вперёд;
  * проверки: картинка существует, CTA-цитата в формате канала, фраза
    призыва не дублирует `cta-phrases.json`;
  * публикация — через `publish_post.py` (он делает upload, POST и GET-контроль);
  * после успеха CTA-фраза дописывается в реестр, пост и реестр коммитятся
    и пушатся;
  * параллельные запуски защищены lock-файлом.

Ручной запуск:
  py roles\\blogger\\tools\\publish_scheduled.py --channel ainow --dry-run
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from shared.paths import CONFIG  # noqa: E402

MSK = timezone(timedelta(hours=3))
LOCK = REPO / "local" / "publish-scheduled.lock"
REPORT = REPO / "local" / "scheduled-publish.txt"
LOG = REPO / "local" / "logs" / "publish-scheduled.log"

LINES = []


def say(line=""):
    LINES.append(line)
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"))


def flush():
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(LINES) + "\n", encoding="utf-8")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write("\n".join(LINES) + "\n")


def read_front_matter(path):
    raw = path.read_text(encoding="utf-8")
    m = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", raw, re.S)
    if not m:
        raise ValueError(f"нет front matter: {path.name}")
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    return fm, m.group(2)


def git(*args):
    return subprocess.run(["git", *args], cwd=str(REPO), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def acquire_lock():
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.close(fd)
        return True
    except FileExistsError:
        age = time.time() - LOCK.stat().st_mtime
        if age > 3600:
            LOCK.unlink(missing_ok=True)
            return acquire_lock()
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="ainow")
    ap.add_argument("--limit", type=int, default=0,
                    help="0 — без ограничения, иначе максимум постов за запуск")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    now = datetime.now(MSK)
    say(f"запуск: {now:%Y-%m-%d %H:%M:%S MSK}, канал: {args.channel}")

    if not LOCK.parent.exists():
        LOCK.parent.mkdir(parents=True, exist_ok=True)
    owned = acquire_lock()
    if not owned:
        say("пропуск: уже идёт другой запуск (lock существует моложе часа)")
        flush()
        return 0

    try:
        return run(args, now)
    finally:
        if owned:
            LOCK.unlink(missing_ok=True)


def run(args, now):
    cfg = json.loads((CONFIG / "channels.json").read_text(encoding="utf-8"))
    ch = next((c for c in cfg["channels"] if c["slug"] == args.channel), None)
    if not ch:
        say(f"FAIL: канал {args.channel!r} не найден в channels.json")
        flush()
        return 1
    cta_label, cta_url = ch["cta_label"], ch["cta_url"]
    cta_re = re.compile(
        rf"^> \*\*Подписывайтесь на \[{re.escape(cta_label)}\]"
        rf"\({re.escape(cta_url)}\)\*\* — (.+)$", re.M)

    posts_dir = REPO / "roles" / "blogger" / "channels" / args.channel / "posts"
    candidates = []
    for path in sorted(posts_dir.glob("*.md")):
        d = re.match(r"^(\d{4}-\d{2}-\d{2})-", path.name)
        if not d:
            continue
        try:
            fm, body = read_front_matter(path)
        except ValueError as e:
            say(f"WARN: {e}")
            continue
        if fm.get("status") != "approved":
            continue
        if fm.get("message_id"):
            say(f"WARN: {path.name} — approved, но message_id уже есть; пропуск")
            continue
        plan_date = datetime.strptime(d.group(1), "%Y-%m-%d").date()
        if plan_date > now.date():
            continue
        candidates.append((path, fm, body, plan_date))

    if not candidates:
        say("нет approved-постов на сегодняшнюю дату — публиковать нечего")
        flush()
        return 0

    limit_text = "без ограничения" if not args.limit else str(args.limit)
    say(f"кандидатов: {len(candidates)}; лимит за запуск: {limit_text}")

    reg_path = posts_dir.parent / "cta-phrases.json"
    registry = json.loads(reg_path.read_text(encoding="utf-8"))

    # origin не должен уйти вперёд: с грязным деревом rebase не сделать
    git("fetch", "origin", "--quiet")
    behind = git("rev-list", "--count", "HEAD..origin/main")
    n_behind = int(behind.stdout.strip() or 0) if behind.returncode == 0 else 0
    if n_behind:
        say(f"FAIL: origin/main впереди на {n_behind} коммит(ов); "
            f"нужно обновить дерево вручную, публикация отложена")
        flush()
        return 1
    dirty = git("status", "--porcelain").stdout.strip()
    if dirty:
        say("WARN: в дереве есть незакоммиченные изменения — pull пропущен "
            "(на публикацию не влияют,origin не опережает)")

    published = 0
    for path, fm, body, plan_date in candidates:
        if args.limit and published >= args.limit:
            break

        img = fm.get("image_file")
        if not img or not (REPO / img).exists():
            say(f"FAIL: {path.name} — нет картинки ({img!r})")
            continue
        m = cta_re.search(body)
        if not m:
            say(f"FAIL: {path.name} — нет CTA-цитаты в формате канала")
            continue
        phrase = m.group(1).strip()
        dup = [k for k, v in registry.items()
               if k not in ("_", path.name) and v == phrase]
        if dup:
            say(f"FAIL: {path.name} — CTA-фраза уже есть у {dup[0]}")
            continue

        say("")
        say(f"публикация: {path.name} (план {plan_date:%d.%m.%Y})")
        if args.dry_run:
            say("DRY-RUN: публикация не выполнялась")
            continue

        env = dict(os.environ)
        env["MAX_HTTP"] = "python"
        ca = REPO / "local" / "russian_ca_bundle.pem"
        if ca.exists():
            env["MAX_CA_CERT"] = str(ca)
        res = subprocess.run(
            [sys.executable, str(REPO / "roles/blogger/tools/publish_post.py"),
             "--channel", args.channel, str(path)],
            cwd=str(REPO), capture_output=True, text=True,
            encoding="utf-8", errors="replace", env=env)
        if res.returncode != 0:
            say(f"FAIL: publish_post вернул {res.returncode}")
            err = (res.stderr or res.stdout or "").strip()
            if err:
                say(err[-1500:])
            continue

        fm_after, _ = read_front_matter(path)
        url = fm_after.get("url", "")
        mid = fm_after.get("message_id", "")
        say(f"OK: {url or mid}")

        registry[path.name] = phrase
        reg_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")

        git("add", str(path.relative_to(REPO)), str(reg_path.relative_to(REPO)))
        msg = f"roles/blogger: publish {path.stem} (scheduled)"
        commit = git("commit", "-m", msg, "--", str(path.relative_to(REPO)),
                     str(reg_path.relative_to(REPO)))
        if commit.returncode != 0:
            say("WARN: git commit не выполнен")
            say((commit.stderr or "").strip()[-500:])
        else:
            say(f"коммит: {git('rev-parse', '--short', 'HEAD').stdout.strip()}")
            push = git("push", "origin", "main")
            if push.returncode != 0:
                say("WARN: git push не выполнен, коммит остался локально")
                say((push.stderr or "").strip()[-500:])
        published += 1

    say("")
    say(f"опубликовано за запуск: {published}")
    say(f"отчёт публикатора: local/publish-{args.channel}.txt")
    flush()
    return 0 if published or args.dry_run else 1


if __name__ == "__main__":
    sys.exit(main())
