# -*- coding: utf-8 -*-
"""Фаза C: проверка, что переносы папок не сломали скрипты и методики.

Запуск:  py shared/verify_layout.py
Отчёт:   local/verify-layout.txt  (полные детали), консоль — только итоги.

Проверки ничего не публикуют и не меняют: сетевых вызовов нет, archive_upload
запускается только в --dry-run с --limit 3.
"""
from __future__ import annotations

import compileall
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared import paths  # noqa: E402
from shared.post_guard import assert_channel_chat_id  # noqa: E402

REPORT: list[str] = []
ERRORS = 0
WARNINGS = 0


def ok(msg: str) -> None:
    REPORT.append(f"OK   {msg}")
    print(f"OK   {msg}")


def warn(msg: str) -> None:
    global WARNINGS
    WARNINGS += 1
    REPORT.append(f"WARN {msg}")
    print(f"WARN {msg}")


def fail(msg: str) -> None:
    global ERRORS
    ERRORS += 1
    REPORT.append(f"FAIL {msg}")
    print(f"FAIL {msg}")


def section(title: str) -> None:
    REPORT.append("")
    REPORT.append(f"== {title} ==")


def check_layout() -> None:
    section("Структура")
    required = [
        ROOT / "roles" / "archivist" / "tools",
        ROOT / "roles" / "archivist" / "docs",
        ROOT / "roles" / "blogger" / "tools",
        ROOT / "roles" / "blogger" / "bin",
        ROOT / "roles" / "blogger" / "config",
        ROOT / "roles" / "blogger" / "channels",
        ROOT / "roles" / "newsbot" / "src",
        ROOT / "shared",
    ]
    for path in required:
        (ok if path.is_dir() else fail)(f"каталог {path.relative_to(ROOT).as_posix()}")
    legacy = ["tools", "bin", "config", "experiments", "channels"]
    for name in legacy:
        path = ROOT / name
        if path.exists():
            fail(f"остался старый каталог {name}/")
        else:
            ok(f"старого каталога {name}/ нет")
    for rel in (
        "AGENTS.md",
        "roles/blogger/bin/post.php",
        "roles/blogger/config/channels.json",
        "shared/paths.py",
        "shared/post_guard.py",
        "roles/newsbot/TASK.md",
        "archive/review.php",
    ):
        (ok if (ROOT / rel).is_file() else fail)(f"файл {rel}")


def check_configs() -> None:
    section("Конфиги и токены")
    cfg_path = paths.CONFIG / "channels.json"
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        channels = cfg["channels"]
        ok(f"{cfg_path.relative_to(ROOT).as_posix()}: каналов {len(channels)}")
    except Exception as exc:  # noqa: BLE001
        fail(f"channels.json не читается: {exc}")
        return

    slugs = [c["slug"] for c in channels]
    dirs = {p.name for p in paths.CHANNELS.iterdir() if p.is_dir()} if paths.CHANNELS.exists() else set()
    for slug in sorted(set(slugs) - dirs):
        fail(f"канал {slug!r} есть в channels.json, но нет папки")
    for slug in sorted(dirs - set(slugs)):
        warn(f"папка канала {slug!r} не описана в channels.json")

    tokens_file = paths.tokens_path()
    if not tokens_file.exists():
        warn("local/tokens.json отсутствует (на этой машине не настроен)")
    else:
        tokens = json.loads(tokens_file.read_text(encoding="utf-8"))
        for slug in slugs:
            entry = tokens.get(slug) or {}
            if not entry.get("token"):
                warn(f"в local/tokens.json нет токена для {slug!r}")
                continue
            chat_id = entry.get("chat_id")
            if chat_id is None:
                warn(f"в local/tokens.json нет chat_id для {slug!r}")
                continue
            try:
                assert_channel_chat_id(chat_id, tool="verify")
                ok(f"токен и канал {slug}: chat_id отрицательный")
            except SystemExit:
                fail(f"{slug}: chat_id не канал ({chat_id})")
        if "newsbot" not in tokens:
            warn("в local/tokens.json нет ключа newsbot")


def check_python() -> None:
    section("Python: компиляция и импорты")
    ok_compile = compileall.compile_dir(str(ROOT / "roles"), quiet=1, force=True)
    ok_compile = compileall.compile_dir(str(ROOT / "shared"), quiet=1, force=True) and ok_compile
    (ok if ok_compile else fail)("py_compile всех файлов roles/ и shared/")

    stale = []
    assignment = re.compile(r"^\s*REPO\s*=\s*Path\(__file__\)\.resolve\(\)\.parent\.parent", re.M)
    for path in list((ROOT / "roles").rglob("*.py")) + list((ROOT / "shared").rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if assignment.search(text):
            stale.append(path)
    if stale:
        for path in stale:
            fail(f"остался parent.parent: {path.relative_to(ROOT).as_posix()}")
    else:
        ok("нет устаревшего Path(__file__).parent.parent")

    # publish_post импортируется безопасно (main под __main__).
    code = (
        "import sys; "
        f"sys.path.insert(0, {str(ROOT / 'roles' / 'blogger' / 'tools')!r}); "
        "import publish_post; print('import ok')"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    (ok if result.returncode == 0 else fail)(
        "импорт publish_post" + ("" if result.returncode == 0 else f": {result.stderr[-300:]}")
    )


def check_smoke() -> None:
    section("Безопасные прогоны")
    commands = [
        ("brief_selftest", [sys.executable, "roles/newsbot/src/brief_selftest.py"], "failures: 0"),
        ("digest_bot registry", [sys.executable, "roles/newsbot/src/digest_bot.py", "registry"], "registry:"),
        ("archive_upload dry-run", [sys.executable, "roles/archivist/tools/archive_upload.py", "--dry-run", "--limit", "3"], "ok:"),
    ]
    for name, cmd, needle in commands:
        try:
            result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired:
            fail(f"{name}: таймаут")
            continue
        if result.returncode == 0 and needle in (result.stdout + result.stderr):
            ok(f"{name}")
        else:
            fail(f"{name}: rc={result.returncode} {(result.stderr or result.stdout)[-300:]}")


def check_guard() -> None:
    section("Сторож публикаций")
    try:
        assert_channel_chat_id(-76964086179165, tool="verify")
        ok("канал (chat_id < 0) разрешён")
    except SystemExit:
        fail("канал ошибочно заблокирован")
    blocked = 0
    for value in (537566305, 0, 1):
        try:
            assert_channel_chat_id(value, tool="verify")
        except SystemExit:
            blocked += 1
    (ok if blocked == 3 else fail)(f"диалоги/группы заблокированы: {blocked} из 3")


def check_paths_in_code() -> None:
    section("Устаревшие пути в коде")
    tool_names = (
        "add_devices_to_plan|archive_plan|archive_upload|collect_devices|dump_channel|"
        "inbox_batch_apply|inbox_batch_dedupe|inbox_batch_download|inbox_batch_plan|"
        "inbox_batch_verify|inbox_delete|patch_plan_missing|build_markdown|dzen_build|"
        "ensure_cta_quote|fetch_images|make_card|markup_fragments|pick_image|"
        "publish_post|publish_telegram|tg_direct|post_guard"
    )
    patterns = [
        (re.compile(rf"(?<!roles/archivist/)(?<!roles/blogger/)tools/(?:{tool_names})\.py"), "tools/<name>.py без роли"),
        (re.compile(r"(?<!roles/blogger/)bin/post\.php"), "bin/post.php без roles/blogger/"),
        (re.compile(r"(?<!roles/blogger/)config/channels\.json"), "config/channels.json без roles/blogger/"),
        (re.compile(r"experiments/personal-news"), "experiments/personal-news"),
        (re.compile(r"(?<!roles/blogger/)channels/(?:ainow|na100|administrator|tg_neuro)"), "канал channels/<slug> без roles/blogger/"),
    ]
    checked = 0
    for path in list((ROOT / "roles").rglob("*.py")) + list((ROOT / "shared").rglob("*.py")):
        if path.name == "verify_layout.py":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern, label in patterns:
            if pattern.search(text):
                fail(f"{path.relative_to(ROOT).as_posix()}: {label}")
        checked += 1
    ok(f"проверено файлов кода: {checked}")


def check_docs_paths() -> None:
    section("Пути в документации")
    doc_files = [ROOT / "AGENTS.md", ROOT / "README.md"] + list((ROOT / "docs").glob("*.md")) + list((ROOT / "roles").rglob("*.md"))
    candidate = re.compile(r"`((?:roles|shared|docs|archive|deploy)/[^`\s]+?\.(?:md|py|php|json|jsonl|pem|example\.json))`")
    missing: list[str] = []
    for path in doc_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for rel in candidate.findall(text):
            if any(ch in rel for ch in "<>*{}"):
                continue  # шаблоны вида <slug>, * — это не конкретный путь
            if not (ROOT / rel).exists():
                missing.append(f"{path.relative_to(ROOT).as_posix()} -> {rel}")
    if missing:
        for item in missing:
            warn(f"ссылка на несуществующий путь: {item}")
    else:
        ok(f"проверено документов: {len(doc_files)}, битых путей нет")


def main() -> int:
    REPORT.extend([
        "Проверка структуры MAX после разделения ролей",
        f"корень: {ROOT}",
        f"python: {sys.version.split()[0]}",
    ])
    check_layout()
    check_configs()
    check_python()
    check_smoke()
    check_guard()
    check_paths_in_code()
    check_docs_paths()

    REPORT.append("")
    REPORT.append(f"ИТОГ: ошибок {ERRORS}, предупреждений {WARNINGS}")
    out = ROOT / "local" / "verify-layout.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(REPORT) + "\n", encoding="utf-8")
    print(f"\nИТОГ: ошибок {ERRORS}, предупреждений {WARNINGS}")
    print(f"отчёт: {out}")
    return 1 if ERRORS else 0


if __name__ == "__main__":
    raise SystemExit(main())
