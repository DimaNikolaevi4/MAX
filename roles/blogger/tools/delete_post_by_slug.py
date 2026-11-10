# -*- coding: utf-8 -*-
"""Удаление поста канала MAX по короткому URL (slug).

Использование:
  python roles/blogger/tools/delete_post_by_slug.py [--channel zabava] <slug>

Что делает:
  * находит сообщение по URL, оканчивающемуся на slug (до 500 последних);
  * проверяет, что найденный mid действительно ведёт на этот slug;
  * DELETE /messages?message_id=...;
  * контроль: GET /messages/{mid} должен вернуть 404.

Коды возврата: 0 — удалено, 1 — ошибка, 4 — пост не найден.
"""

import json
import re
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(r"E:\github\MAX")
TOKENS = REPO / "local" / "tokens.json"
CA = REPO / "local" / "russian_ca_bundle.pem"


def api(token: str, method: str, path: str) -> tuple[int, str]:
    ctx = ssl.create_default_context()
    if CA.exists():
        ctx.load_verify_locations(cafile=str(CA))
    req = urllib.request.Request("https://platform-api2.max.ru" + path, method=method,
                                 headers={"Authorization": token,
                                          "User-Agent": "curl/8.13.0"})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=90) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


def find_message(token: str, chat_id: int, slug: str) -> dict | None:
    marker = None
    for _ in range(5):
        path = f"/messages?chat_id={chat_id}&count=100" + (f"&marker={marker}" if marker else "")
        code, body = api(token, "GET", path)
        if code != 200:
            raise SystemExit(f"GET /messages HTTP {code}: {body[:200]}")
        data = json.loads(body)
        for msg in (data.get("messages") or []):
            if str(msg.get("url") or "").rstrip("/").endswith(slug):
                return msg
        marker = data.get("marker")
        if not marker:
            break
    return None


def delete_message(token: str, mid: str) -> tuple[int, str]:
    return api(token, "DELETE", f"/messages?message_id={mid}")


def mark_deleted(channel: str, slug: str, mid: str) -> Path | None:
    """Помечает файл поста: status: deleted + deleted_at (для календаря блогера)."""
    posts = REPO / "roles" / "blogger" / "channels" / channel / "posts"
    if not posts.exists():
        return None
    now = datetime.now(timezone(timedelta(hours=3))).isoformat(timespec="seconds")
    for path in sorted(posts.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        m = re.match(r"\A---\r?\n(.*?)\r?\n---", raw, re.S)
        if not m:
            continue
        fm_text = m.group(1)
        fm = {}
        for line in fm_text.splitlines():
            if ":" in line and not line.startswith((" ", "\t")):
                key, value = line.split(":", 1)
                fm[key.strip()] = value.strip()
        url = (fm.get("url") or "").rstrip("/")
        if not (url.endswith(slug) or fm.get("message_id") == mid):
            continue
        lines, seen_status, seen_deleted = [], False, False
        for line in fm_text.splitlines():
            key = line.split(":", 1)[0].strip() if ":" in line else ""
            if key == "status":
                lines.append("status: deleted")
                seen_status = True
            elif key == "deleted_at":
                lines.append(f"deleted_at: {now}")
                seen_deleted = True
            else:
                lines.append(line)
        if not seen_status:
            lines.insert(0, "status: deleted")
        if not seen_deleted:
            lines.insert(1, f"deleted_at: {now}")
        sep = "\r\n" if "\r\n" in raw else "\n"
        head, tail = raw[:m.start(1)], raw[m.end(1):]
        path.write_text(head + sep.join(lines) + tail, encoding="utf-8", newline="")
        return path
    return None


def git(*args: str):
    return subprocess.run(["git", *args], cwd=str(REPO), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def commit_mark(path: Path, channel: str, slug: str) -> None:
    rel = path.relative_to(REPO).as_posix()
    git("add", rel)
    commit = git("commit", "-m", f"channels: {channel} — пост удалён ({slug})", "--", rel)
    if commit.returncode != 0:
        print("WARN: git commit не выполнен, отметка осталась в рабочем дереве")
        return
    push = git("push", "origin", "main")
    if push.returncode != 0:
        print("WARN: git push не выполнен, коммит остался локально")


def main() -> None:
    args = sys.argv[1:]
    channel = "zabava"
    if "--channel" in args:
        i = args.index("--channel")
        channel = args[i + 1]
        del args[i:i + 2]
    if len(args) != 1:
        raise SystemExit("Использование: delete_post_by_slug.py [--channel zabava] <slug>")
    slug = args[0].rstrip("/").split("/")[-1]

    entry = json.loads(TOKENS.read_text(encoding="utf-8"))[channel]
    token = entry["token"]
    chat_id = int(entry["chat_id"])

    msg = find_message(token, chat_id, slug)
    if not msg:
        print(f"NOT FOUND: {slug} в последних сообщениях канала")
        raise SystemExit(4)
    mid = (msg.get("body") or {}).get("mid")
    url = msg.get("url") or ""
    if not mid:
        print(f"FAIL: у сообщения {slug} нет mid")
        raise SystemExit(1)
    if not url.rstrip("/").endswith(slug):
        print(f"FAIL: mid ведёт на {url}, а не на {slug}")
        raise SystemExit(1)

    code, body = delete_message(token, mid)
    if code != 200:
        print(f"FAIL: DELETE HTTP {code}: {body[:300]}")
        raise SystemExit(1)

    check_code, _ = api(token, "GET", f"/messages/{mid}")
    if check_code != 404:
        print(f"FAIL: после удаления GET вернул {check_code}, ожидался 404")
        raise SystemExit(1)

    print(f"DELETED: {slug} (mid={mid}), GET=404")

    marked = mark_deleted(channel, slug, mid)
    if marked:
        print(f"пост помечен как удалённый: {marked.relative_to(REPO).as_posix()}")
        commit_mark(marked, channel, slug)
    else:
        print(f"WARN: файл поста со slug {slug} не найден — отметка об удалении не поставлена")
    print(json.dumps({"slug": slug, "mid": mid, "deleted": True, "marked": bool(marked)}))


if __name__ == "__main__":
    main()
