# -*- coding: utf-8 -*-
"""Генерация рабочего webhook-файла бота AI Now (секреты НЕ печатаются).

Читает ключ newsbot из local/tokens.json (токен @se14808890_bot,
owner_user_id/owner_chat_id если заданы), шаблон
roles/newsbot/hosting/bot1_webhook_template.php, генерирует случайный
секрет (только A-Za-z0-9_- по требованиям MAX) и пишет
local/hosting/bot1_webhook.php — готовый к загрузке на хостинг.

Запуск:  py roles\\newsbot\\tools\\gen_bot1_webhook.py
"""
import json
import secrets
from pathlib import Path

REPO = next(p for p in Path(__file__).resolve().parents
            if (p / ".git").exists())
OUT = REPO / "local" / "hosting"
OUT.mkdir(parents=True, exist_ok=True)

entry = json.loads((REPO / "local" / "tokens.json").read_text(
    encoding="utf-8")).get("newsbot", {})
token = entry.get("token")
if not token:
    raise SystemExit("нет ключа newsbot в local/tokens.json")

owner_user = str(entry.get("owner_user_id") or "3623517")
owner_chat = str(entry.get("owner_chat_id") or "537566305")

# Секрет MAX: 5-256 символов, только A-Za-z0-9_- (token_urlsafe подходит)
secret = secrets.token_urlsafe(24)

tpl = (REPO / "roles" / "newsbot" / "hosting"
       / "bot1_webhook_template.php").read_text(encoding="utf-8")
php = (tpl.replace("{{TOKEN}}", token)
          .replace("{{SECRET}}", secret)
          .replace("{{OWNER_USER_ID}}", owner_user)
          .replace("{{OWNER_CHAT_ID}}", owner_chat))
(OUT / "bot1_webhook.php").write_text(php, encoding="utf-8")
print("ok: local/hosting/bot1_webhook.php сгенерирован "
      f"(owner_user={owner_user}, owner_chat={owner_chat}, секрет не печатается)")
