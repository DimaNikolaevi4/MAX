# -*- coding: utf-8 -*-
"""Имитация события MAX на webhook бота AI Now (тест цепочки без платформы).

Формирует событие (по умолчанию bot_started) и шлёт POST на
https://0s3.ru/bot1/bot1_webhook.php — секрет берётся из
local/hosting/bot1_webhook.php, передаётся и в query (?s=), и в заголовке
X-Max-Bot-Api-Secret. Обработчик отвечает 'ok' и обрабатывает событие:
это проверяет весь путь PHP -> API MAX (включая CA Минцифры).

Использование:
  py roles\\newsbot\\tools\\simulate_bot1_webhook.py                  # bot_started владельцу
  py roles\\newsbot\\tools\\simulate_bot1_webhook.py message_created 537566305 "тест"

ВНИМАНИЕ: message_created с user_id владельца PHP трактует как «отв <id>»
— для проверки квитанции указывайте чужой user_id (запись попадёт в реестр).

Секрет и токен не печатаются.
"""
import json
import re
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = next(p for p in Path(__file__).resolve().parents
            if (p / ".git").exists())
PHP = REPO / "local" / "hosting" / "bot1_webhook.php"
URL = "https://0s3.ru/bot1/bot1_webhook.php"

upd_type = sys.argv[1] if len(sys.argv) > 1 else "bot_started"
chat_id = int(sys.argv[2]) if len(sys.argv) > 2 else 537566305
text = sys.argv[3] if len(sys.argv) > 3 else ""

php = PHP.read_text(encoding="utf-8")
secret = re.search(r"const SECRET\s*=\s*'([^']+)'", php).group(1)

upd = {"update_type": upd_type, "chat_id": chat_id,
       "user": {"user_id": chat_id, "name": "владелец"}}
if upd_type in ("message_created", "message_edited"):
    upd["message"] = {
        "recipient": {"chat_type": "dialog", "chat_id": chat_id},
        "sender": {"user_id": chat_id, "is_bot": False},
        "body": {"mid": f"sim.{chat_id}", "text": text or "тест"},
    }

ctx = ssl.create_default_context()
ca = REPO / "local" / "russian_ca_bundle.pem"
if ca.exists():
    ctx.load_verify_locations(cafile=str(ca))

req = urllib.request.Request(
    URL, data=json.dumps(upd, ensure_ascii=False).encode("utf-8"), method="POST")
req.add_header("Content-Type", "application/json")
req.add_header("User-Agent", "curl/8.13.0")
req.add_header("X-Max-Bot-Api-Secret", secret)

try:
    with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
        print("POST webhook -> HTTP", r.status, r.read().decode("utf-8"))
except urllib.error.HTTPError as e:
    print("POST webhook FAIL -> HTTP", e.code,
          (e.read() or b"").decode("utf-8", "replace")[:200])
    raise SystemExit(1)
