# Одноразовый опрос GET /updates (long polling). Для ручных проверок Ч1-Ч3.
# Использование: py experiments/personal-news/updates_once.py [timeout_sec]
#   timeout_sec 0..90, по умолчанию 0 (мгновенно).
# Результат: печатает ASCII-сводку, полный JSON кладёт в local/updates_last.json,
# маркер long polling хранит в local/pnews_pollstate.json (домен эксперимента).
import json
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / "local"
STATE = LOCAL / "pnews_pollstate.json"
LAST = LOCAL / "updates_last.json"
API = "https://platform-api2.max.ru/updates"


def ca_context() -> ssl.SSLContext:
    cafile = LOCAL / "russian_ca_bundle.pem"
    return ssl.create_default_context(cafile=cafile) if cafile.exists() else ssl.create_default_context()


def http_get(url: str, token: str, ctx: ssl.SSLContext) -> bytes:
    req = urllib.request.Request(url, headers={"Authorization": token, "User-Agent": "curl/8.13.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=120) as resp:
        return resp.read()


def main() -> int:
    timeout = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    token = (json.loads((LOCAL / "tokens.json").read_text(encoding="utf-8")))["newsbot"]["token"]

    params = [f"timeout={timeout}"]
    if STATE.exists():
        state = json.loads(STATE.read_text(encoding="utf-8"))
        marker = state.get("marker")
        if marker is not None:
            params.append(f"marker={int(marker)}")

    url = f"{API}?{'&'.join(params)}"
    try:
        body = http_get(url, token, ca_context())
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code} (error)", e.read().decode("utf-8", "replace")[:300])
        return 1

    data = json.loads(body.decode("utf-8"))
    LAST.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    updates = data.get("updates") or []
    new_marker = data.get("marker")
    if new_marker is not None:
        STATE.write_text(json.dumps({"marker": new_marker}), encoding="utf-8")

    print(f"updates: {len(updates)} | marker_saved: {new_marker is not None}")
    for u in updates:
        m = u.get("message") or {}
        r = m.get("recipient") or {}
        b = m.get("body") or {}
        sender = (m.get("sender") or {}).get("is_bot")
        text = b.get("text") or ""
        print(f"  type={u.get('update_type')} chat={r.get('chat_type')}/{r.get('chat_id')} "
              f"sender_is_bot={sender} mid={str(b.get('mid'))[:16]} text_len={len(text)}")
    print("full json: local/updates_last.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
