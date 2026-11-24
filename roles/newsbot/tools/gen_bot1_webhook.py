# -*- coding: utf-8 -*-
"""Генерация рабочего webhook-файла бота AI Now (секреты НЕ печатаются).

Читает ключ newsbot из local/tokens.json (токен @se14808890_bot,
owner_user_id/owner_chat_id если заданы), шаблон
roles/newsbot/hosting/bot1_webhook_template.php, и пишет
local/hosting/bot1_webhook.php — готовый к загрузке на хостинг.

Секрет: по умолчанию СОХРАНЯЕТСЯ из существующего рабочего файла (подписка
активна — перевыпуск секрета оборвёт поток событий). Новый секрет — только
если файла нет или указан --new-secret (тогда нужен recreate подписки).

Запуск:  py roles\\newsbot\\tools\\gen_bot1_webhook.py [--new-secret]
"""
import json
import re
import secrets
import sys
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

existing = OUT / "bot1_webhook.php"
secret = None
if "--new-secret" not in sys.argv and existing.exists():
    m = re.search(r"const SECRET\s*=\s*'([^']+)'",
                  existing.read_text(encoding="utf-8"))
    if m:
        secret = m.group(1)
if secret:
    print("ok: секрет сохранён из существующего файла (подписка не менялась)")
else:
    # Секрет MAX: 5-256 символов, только A-Za-z0-9_- (token_urlsafe подходит)
    secret = secrets.token_urlsafe(24)
    print("ok: секрет сгенерирован новый — если подписка уже активна, "
          "нужен recreate подписки")

tpl = (REPO / "roles" / "newsbot" / "hosting"
       / "bot1_webhook_template.php").read_text(encoding="utf-8")
php = (tpl.replace("{{TOKEN}}", token)
          .replace("{{SECRET}}", secret)
          .replace("{{OWNER_USER_ID}}", owner_user)
          .replace("{{OWNER_CHAT_ID}}", owner_chat))
(OUT / "bot1_webhook.php").write_text(php, encoding="utf-8")
print("ok: local/hosting/bot1_webhook.php сгенерирован "
      f"(owner_user={owner_user}, owner_chat={owner_chat}, секрет не печатается)")
