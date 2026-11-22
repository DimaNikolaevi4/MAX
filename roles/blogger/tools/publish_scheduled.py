# -*- coding: utf-8 -*-
"""Публикация постов со `status: approved` по расписанию (Планировщик Windows).

Логика запуска:
  * берутся посты канала со `status: approved`, у которых дата из имени файла
    не позже сегодняшней (МСК);
  * за один запуск публикуются все готовые посты (`--limit 0` — без ограничения);
  * перед публикацией: `git fetch`, отказ, если origin/main ушёл вперёд;
  * проверки: медиа (картинка или видео) существует, CTA-цитата в формате
    канала, фраза
    призыва не дублирует `cta-phrases.json`;
   * общий движок проверки — shared/format_core.py (FORMAT CORE v1);
   * publish_window — окно догона [start_hour, end_hour] или null;
   * текстовые посты catden проходят без медиа; новый пост ядра — с format_core: 1;
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
from shared import format_core  # noqa: E402

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
    """Front matter с сохранением всех полей (format_core) + тело поста."""
    raw = path.read_text(encoding="utf-8")
    if not re.match(r"\A---\r?\n", raw):
        raise ValueError(f"нет front matter: {path.name}")
    fm, body = format_core.split_post(raw)
    return fm, body


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


def resolve_media(name: str):
    """Абсолютный путь к файлу медиа по значению image_file/video_file.

    Методика (явная, без пробелов и неоднозначностей):
      1) имя с префиксом (local/...) — путь от корня репозитория;
      2) bare-имя — сначала корень репозитория, затем локализация инструментов
         (local/images/<имя>, local/media-cache/<имя>).
    Возвращает None, если файл нигде не найден.
    """
    if not name:
        return None
    cand = REPO / name
    if cand.exists():
        return cand
    if "/" not in name:
        for sub in ("local/images", "local/media-cache"):
            alt = REPO / sub / name
            if alt.exists():
                return alt
    return None


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
    # CTA-адресат может отличаться у поста (cta_target: self|ainow) — см.
    # format_core.resolve_cta; реестр фраз проверяется ниже по тексту поста.

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

    # publish_window — окно догона, а не жёсткое время публикации.
    window = format_core.parse_publish_window(ch.get("publish_window"))
    if window and not (window[0] <= now.hour <= window[1]):
        say(f"вне окна догона {window[0]:02d}:00-{window[1]:02d}:00 "
            f"({now:%Y-%m-%d %H:%M MSK}) — публикация отложена")
        flush()
        return 0

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

        # Единый движок формата: заголовок, воздух, CTA адресату, вопрос,
        # реакции, лимиты, вёрстка, перелинковка, медиа и запрещённые орги.
        core_result = format_core.check_post(
            path, channel=args.channel, for_publish=True,
            check_spellcheck=False, resolve_media_path_fn=resolve_media)
        for issue in core_result.issues:
            say(str(issue))
        if not core_result.ok:
            say(f"FAIL: {path.name} — format_core не прошёл")
            continue

        media = fm.get("image_file") or fm.get("video_file")
        image_files = [x.strip() for x in (fm.get("image_files") or "").split("|") if x.strip()]
        missing_media = [f for f in image_files if resolve_media(f) is None]
        if image_files and missing_media:
            say(f"FAIL: {path.name} — нет картинок альбома: {missing_media[:2]}")
            continue
        if not image_files and not media and not fm.get("video_source"):
            # Текстовые посты разрешены профилем (catden); для остальных
            # каналов отсутствие медиа — ошибка.
            text_only = bool(ch.get("allow_text_only")) or args.channel == "catden"
            if not text_only:
                say(f"FAIL: {path.name} — нет медиа ({media!r})")
                continue

        cta = format_core.resolve_cta(args.channel, fm, ch)
        cta_re = re.compile(
            rf"^> \*\*Подписывайтесь на \[{re.escape(cta['label'])}\]"
            rf"\({re.escape(cta['url'])}\)\*\* — (.+)$", re.M)
        m = cta_re.search(body)
        if not m:
            say(f"FAIL: {path.name} — нет CTA-цитаты для адресата {cta['target']}")
            continue
        phrase = m.group(1).strip()
        # окно 6 (правило zabava 08.11, расширено на все каналы 12.11.2026):
        # фраза не должна повторяться в последних 6 записях реестра
        recent = [v for k, v in list(registry.items())[-6:] if k != "_"]
        dup = [k for k, v in registry.items()
               if k not in ("_", path.name) and v == phrase and v in recent]
        if dup:
            say(f"FAIL: {path.name} — CTA-фраза повторяется в окне 6 ({dup[0]})")
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




def _refresh_calendar_plan() -> None:
    """Пересобрать plan.json для общего календаря: опубликованные посты -> done."""
    try:
        import subprocess, sys
        subprocess.run(
            [sys.executable, str(REPO / "roles" / "blogger" / "tools" / "export_plan.py")],
            cwd=str(REPO), capture_output=True, timeout=120)
    except Exception:
        pass

if __name__ == "__main__":
    rc = main()
    # DRY-RUN не должен пересобирать общий календарь: это побочная запись.
    if "--dry-run" not in sys.argv:
        _refresh_calendar_plan()
    sys.exit(rc)
