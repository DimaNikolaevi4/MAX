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
import ssl
import sys
import urllib.error
import urllib.request
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
    print(json.dumps({"slug": slug, "mid": mid, "deleted": True}))


if __name__ == "__main__":
    main()
