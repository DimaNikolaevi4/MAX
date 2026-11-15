# -*- coding: utf-8 -*-
"""Подписка бота AI Now (@se14808890_bot) на webhook (POST /subscriptions).

URL берётся из https://0s3.ru/bot1/bot1_webhook.php + секрет из
local/hosting/bot1_webhook.php. Секрет и токен не печатаются.

Запуск:  py roles\\newsbot\\tools\\subscribe_bot1_webhook.py
"""
import json
import re
import ssl
import urllib.error
import urllib.request
from pathlib import Path

REPO = next(p for p in Path(__file__).resolve().parents
            if (p / ".git").exists())
LOCAL = REPO / "local"

token = json.loads((LOCAL / "tokens.json").read_text(encoding="utf-8"))["newsbot"]["token"]
secret = re.search(r"const SECRET\s*=\s*'([^']+)'",
                   (LOCAL / "hosting" / "bot1_webhook.php").read_text(encoding="utf-8")).group(1)
url = "https://0s3.ru/bot1/bot1_webhook.php?s=" + secret

ctx = ssl.create_default_context()
ca = LOCAL / "russian_ca_bundle.pem"
if ca.exists():
    ctx.load_verify_locations(cafile=str(ca))

body = json.dumps({"url": url}, ensure_ascii=False).encode("utf-8")
req = urllib.request.Request("https://platform-api2.max.ru/subscriptions",
                             data=body, method="POST")
req.add_header("Authorization", token)
req.add_header("User-Agent", "curl/8.13.0")
req.add_header("Content-Type", "application/json")

out = []
try:
    with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
        r.read()
    out.append("POST /subscriptions: 200")
except urllib.error.HTTPError as e:
    out.append("POST /subscriptions FAIL %s: %s" % (
        e.code, (e.read() or b"").decode("utf-8", "replace")[:300]))

# контроль: список подписок (секрет маскируем)
req2 = urllib.request.Request("https://platform-api2.max.ru/subscriptions")
req2.add_header("Authorization", token)
req2.add_header("User-Agent", "curl/8.13.0")
with urllib.request.urlopen(req2, context=ctx, timeout=60) as r2:
    subs = json.loads(r2.read().decode("utf-8")).get("subscriptions", [])
out.append("подписок сейчас: %d" % len(subs))
for s in subs:
    out.append("  - " + s.get("url", "").split("?")[0] + "?s=***")

(LOCAL / "bot1-subscribe-report.txt").write_text("\n".join(out), encoding="utf-8")
print("\n".join(out))
