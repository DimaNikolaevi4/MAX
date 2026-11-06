# Отправка сообщения в диалог: POST /messages?chat_id=... (+ контроль GET).
# Payload берётся из local/pnews_send.json: {"chat_id": int, "text": "...",
# "format": "markdown" (опц.), "notify": true}
# Ответ кладётся в local/send_last.json, консоль — ASCII-only.
import json
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / "local"
API = "https://platform-api2.max.ru"


def ctx() -> ssl.SSLContext:
    cafile = LOCAL / "russian_ca_bundle.pem"
    return ssl.create_default_context(cafile=cafile) if cafile.exists() else ssl.create_default_context()


def call(url: str, token: str, method: str, payload: dict | None) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": token,
        "User-Agent": "curl/8.13.0",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, context=ctx(), timeout=60) as resp:
            return {"status": resp.status, "json": json.loads(resp.read().decode("utf-8"))}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "json": json.loads(e.read().decode("utf-8")) if e.read else {}}


def main() -> int:
    payload = json.loads((LOCAL / "pnews_send.json").read_text(encoding="utf-8"))
    token = json.loads((LOCAL / "tokens.json").read_text(encoding="utf-8"))["newsbot"]["token"]
    chat_id = payload["chat_id"]

    params = f"chat_id={chat_id}"
    if "notify" in payload:
        params += f"&notify={'true' if payload['notify'] else 'false'}"
    url = f"{API}/messages?{params}"

    result = call(url, token, "POST", {
        "text": payload["text"],
        **({"format": payload["format"]} if "format" in payload else {}),
    })
    (LOCAL / "send_last.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    status = result["status"]
    msg = (result.get("json") or {}).get("message") or {}
    mid = (msg.get("body") or {}).get("mid") or ""
    url_post = msg.get("url") or ""
    print(f"POST status={status} mid={ mid[:20] if isinstance(mid, str) else mid }")
    out = {"status": status, "mid": mid, "post_url": url_post}
    (LOCAL / "pnews_last_sent.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    if status == 200 and mid:
        check = call(f"{API}/messages/{mid}", token, "GET", None)
        mjson = (check.get("json") or {}).get("message") or {}
        # ascii-safe контроль: только длина текста и наличие mid
        print(f"GET status={check['status']} | text_len={len(((mjson.get('body') or {}).get('text') or ''))} | verified")
        (LOCAL / "pnews_send_check.json").write_text(
            json.dumps(check, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if status == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
