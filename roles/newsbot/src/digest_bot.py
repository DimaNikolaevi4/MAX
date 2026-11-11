# digest_bot.py — ядро «личного новостного бота» (фаза 1).
# Команды (ASCII-safe вывод, кириллица только в файлы локали):
#   py digest_bot.py poll [timeout_sec]   опрос /updates + обработка диалогов
#   py digest_bot.py digest [dry]         отправка подошедших дайджестов (позже)
#   py digest_bot.py registry             сводка реестра
#
# Реестр: local/pnews_registry.json. Маркер long polling: local/pnews_pollstate.json.
# Журнал подписок/отписок: local/pnews_churn.jsonl (пишет ТОЛЬКО poll —
# /updates доставляет события один раз, второй консьюмер их не увидит;
# stats_snapshot.py читает журнал, но сам /updates не вызывает).
# Гигиена (TASK.md): только /updates, GET /messages/{mid}, POST /messages в диалоги.
from __future__ import annotations

import datetime
import json
import re
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / ".git").exists())))
from shared.paths import REPO as ROOT  # noqa: E402
LOCAL = ROOT / "local"
REGISTRY_PATH = LOCAL / "pnews_registry.json"
POLLSTATE_PATH = LOCAL / "pnews_pollstate.json"
CHURN_PATH = LOCAL / "pnews_churn.jsonl"
LOG_PATH = LOCAL / "pnews_log.csv"
API = "https://platform-api2.max.ru"

# Решение владельца 11.11.2026: БОТ ПОКА МОЛЧИТ. Автоответы (приветствие
# на «Старт», квитанция на обращения) отключены до переезда поллера на
# хостинг (PHP-скрипт, always-on): ПК владельца работает не круглосуточно,
# при выключенном ПК человек получал бы ответ с задержкой, а при паузах
# дольше окна хранения /updates (~сутки) первый контакт терялся вовсе.
# poll при этом продолжает работать: журнал подписок/отписок (чирн) для
# снапшота 07:00 и фиксация контактов в реестре — без единой отправки.
# Вернуть автоответы: AUTO_REPLY = True.
AUTO_REPLY = False

sys.path.insert(0, str(Path(__file__).resolve().parent))
from brief import FORM_HINT, is_stop, parse_brief  # noqa: E402


# ---------- транспорт ----------

def api_context() -> ssl.SSLContext:
    cafile = LOCAL / "russian_ca_bundle.pem"
    return ssl.create_default_context(cafile=cafile) if cafile.exists() else ssl.create_default_context()


def api_call(token: str, path: str, method: str = "GET", payload: dict | None = None) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(f"{API}{path}", data=body, method=method, headers={
        "Authorization": token,
        "User-Agent": "curl/8.13.0",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, context=api_context(), timeout=120) as resp:
            return {"status": resp.status, "json": json.loads(resp.read().decode("utf-8"))}
    except urllib.error.HTTPError as e:
        raw = b""
        try:
            raw = e.read() or b""
        except Exception:
            pass
        return {"status": e.code, "json": {}, "error_text": raw.decode("utf-8", "replace")[:200]}


def load_token() -> str:
    return json.loads((LOCAL / "tokens.json").read_text(encoding="utf-8"))["newsbot"]["token"]


# ---------- persist ----------

def load_registry() -> dict:
    if REGISTRY_PATH.exists():
        return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return {"users": {}}


def save_registry(reg: dict) -> None:
    REGISTRY_PATH.write_text(json.dumps(reg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def log_line(event: str, detail: str) -> None:
    now = datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat(timespec="seconds")
    entry = f"{now} | {event} | {detail}\n"
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(entry)


# ---------- доставка ----------

def send_dialog(token: str, chat_id: int, text: str) -> tuple[int, str]:
    res = api_call(token, f"/messages?chat_id={chat_id}&notify=true", "POST", {
        "text": text,
        "format": "markdown",
    })
    mid = ((res.get("json") or {}).get("message") or {}).get("body") or {}
    mid = mid.get("mid", "") if isinstance(mid, dict) else ""
    log_line("send", f"chat={chat_id} status={res['status']} mid={mid}")
    return res["status"], mid


# ---------- тексты ответов ----------

# Приветствие на «Старт» (текст владельца 11.11.2026, дословно).
GREETING_TEXT = (
    "Я бот — волшебная палочка. Как и мой хозяин, могу почти всё. "
    "Сейчас помогаю ему вести каналы:\n\n"
    "• «Забавное» — https://max.ru/channel_zabava\n"
    "• «Новости технологий ИИ, нейросетей и инноваций» — https://max.ru/channel_na100\n"
    "• «AI» — https://max.ru/channel_ainow\n\n"
    "Если у вас есть вопрос или нужна помощь — особенно в сфере IT — напишите "
    "здесь. Единственное, что нам не подвластно, — время, а помощь нужна "
    "многим. Но если напишете что-то интересное, обязательно ответим и "
    "постараемся помочь."
)

# Автоответ-квитанция на любое обращение (решение владельца 11.11.2026:
# фикс-текст сразу, содержательный ответ — когда владелец прочтёт;
# копия обращения пересылается в его диалог с ботом).
ACK_TEXT = (
    "✅ Ваше сообщение принято. Отвечаем по мере прочтения — "
    "как только освободимся, ответим здесь же."
)

# Ответ владельца из своего диалога с ботом: «отв <user_id> текст».
REPLY_RE = re.compile(r"^\s*(?:отв|ответ)\s+(\d+)\s*[:\-—]?\s*(.+)$", re.S)

FREQUENCY_LABEL = {
    "daily": "раз в день",
    "twice": "дважды в день (утром и вечером)",
}


def frequency_text(freq: dict) -> str:
    label = FREQUENCY_LABEL.get(freq.get("kind"), "раз в день")
    extras = []
    if freq.get("weekdays_only"):
        extras.append("только будни")
    if freq.get("hour_hint") == "evening":
        extras.append("вечером")
    if freq.get("hour_hint") == "morning":
        extras.append("утром")
    return " — ".join([label] + extras)


def receipt_text(user: dict, warnings: list[str]) -> str:
    parts = [
        f"**Настройка принята**",
        f"• Темы: {', '.join(user.get('themes') or [])}",
        f"• Частота: {frequency_text(user.get('frequency') or {})}",
    ]
    sources = user.get("sources") or []
    if sources:
        parts.append(f"• Источники: {', '.join(sources)}")
    else:
        parts.append("• Источники: не заданы")
    body = "\n\n".join(parts)
    if warnings:
        body += "\n\n" + "\n".join("· " + w for w in warnings)
    body += (
        "\n\nПеренастроить: напишите новое сообщение «темы: …». "
        "Остановить: напишите «стоп»."
    )
    return body


# ---------- обработка событий ----------

def remember_mid(user: dict, mid: str) -> None:
    seen = user.setdefault("seen_mids", [])
    if mid and mid not in seen:
        seen.append(mid)
    if len(seen) > 200:
        del seen[:-200]


def load_owner() -> tuple[int, int]:
    """user_id и chat_id владельца (его диалог с ботом). Приоритет —
    tokens.json (newsbot: owner_user_id / owner_chat_id), ниже — константы."""
    try:
        entry = json.loads((LOCAL / "tokens.json").read_text(encoding="utf-8")).get("newsbot", {})
        return (int(entry.get("owner_user_id") or 3623517),
                int(entry.get("owner_chat_id") or 537566305))
    except Exception:
        return 3623517, 537566305


def owner_reply(token: str, reg: dict, text: str) -> None:
    """Ответ владельца из своего диалога: «отв <user_id> текст».
    Работает и при AUTO_REPLY=False (инициатива всегда исходит от владельца)."""
    owner_id, owner_chat = load_owner()
    m = REPLY_RE.match(text)
    if not m:
        send_dialog(token, owner_chat,
                    "Формат ответа: «отв <id> <текст>» — id есть в пересланных "
                    "обращениях. Например: отв 326451299 Здравствуйте!")
        log_line("owner_reply_fail", "bad format")
        return
    target = reg["users"].get(m.group(1))
    if not target or not target.get("dialog_chat_id"):
        send_dialog(token, owner_chat,
                    f"Нет диалога с пользователем {m.group(1)} в реестре — "
                    "он не стартовал бота или диалог не зафиксирован.")
        log_line("owner_reply_fail", f"no dialog {m.group(1)}")
        return
    status, _ = send_dialog(token, target["dialog_chat_id"], m.group(2).strip())
    log_line("owner_reply", f"-> {m.group(1)} status={status}")


def forward_inquiry(token: str, reg: dict, user: dict, user_id: str, text: str) -> None:
    """Квитанция автору обращения + копия в диалог владельца."""
    _, owner_chat = load_owner()
    send_dialog(token, user.get("dialog_chat_id"), ACK_TEXT)
    stamp = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3)))
    fwd = (f"**Обращение** от {user.get('owner_name') or 'без имени'} "
           f"(id {user_id}, {stamp:%H:%M}):\n\n{text[:2000]}")
    send_dialog(token, owner_chat, fwd)
    log_line("inquiry", f"owner={user_id} len={len(text)}")


def process_message(token: str, reg: dict, mid: str, sender: dict, text: str) -> None:
    owner_user_id = str((sender or {}).get("user_id") or "")
    if not owner_user_id:
        return
    if (sender or {}).get("is_bot"):
        return  # Ч5: свои сообщения бота не парсим

    owner_id, _ = load_owner()
    if owner_user_id == str(owner_id):
        # сообщения владельца в его диалоге = ручные ответы адресатам
        owner_reply(token, reg, text)
        return

    user = reg["users"].get(owner_user_id) or {
        "owner_user_id": int(owner_user_id),
        "owner_name": f"{sender.get('first_name', '')} {sender.get('last_name', '')}".strip(),
    }
    remember_mid(user, mid)

    if is_stop(text):
        user["state"] = "stopped"
        reg["users"][owner_user_id] = user
        save_registry(reg)
        log_line("stop", f"owner={owner_user_id}")
        return

    is_brief_attempt = "темы:" in text.lower()
    parsed = parse_brief(text) if is_brief_attempt else {"ok": False, "reason": ""}
    if is_brief_attempt and not parsed["ok"]:
        # человек пытался задать дайджест, но с ошибками формы
        reply = f"Не распознал настройку.\n\n{parsed['reason']}\n\n{FORM_HINT}"
        if user.get("dialog_chat_id"):
            send_dialog(token, user["dialog_chat_id"], reply)
        reg["users"][owner_user_id] = user
        save_registry(reg)
        log_line("brief_fail", f"owner={owner_user_id}")
        return
    if not parsed["ok"]:
        # обычное обращение: квитанция + копия владельцу (только при
        # AUTO_REPLY; в консервации — фиксируем контакт молча)
        reg["users"][owner_user_id] = user
        save_registry(reg)
        if AUTO_REPLY:
            forward_inquiry(token, reg, user, owner_user_id, text)
        else:
            log_line("inquiry_silent", f"owner={owner_user_id} len={len(text)}")
        return

    user.update({
        "state": "active",
        "themes": parsed["themes"],
        "frequency": parsed["frequency"],
        "sources": parsed["sources"],
        "brief_text": text[-2000:],
        "configured_at": datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat(timespec="seconds"),
        "last_digest_at": user.get("last_digest_at"),
    })
    reg["users"][owner_user_id] = user
    save_registry(reg)
    log_line("brief_ok", f"owner={owner_user_id} themes={parsed['themes']}")
    send_dialog(token, user.get("dialog_chat_id"), receipt_text(user, parsed.get("warnings") or []))


def record_churn(update: dict) -> None:
    """Подписки/отписки каналов бота — в журнал для stats_snapshot.py.
    Вызывается ДО фильтра лички: события канальных чатов в обработку
    диалогов не идут, но в журнал попадают все."""
    if update.get("update_type") not in ("user_added", "user_removed"):
        return
    chat_id = update.get("chat_id")
    if not isinstance(chat_id, int) or chat_id >= 0:
        return  # интересуют только каналы/группы
    u = update.get("user") or {}
    ts = update.get("timestamp") or 0
    rec = {
        "ts": datetime.datetime.fromtimestamp(
            ts / 1000, datetime.timezone(datetime.timedelta(hours=3))).isoformat() if ts else "",
        "event": update["update_type"],
        "chat_id": chat_id,
        "user_id": u.get("user_id"),
        "name": (u.get("name") or "").strip(),
    }
    with CHURN_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def process_bot_started(token: str, reg: dict, update: dict) -> None:
    """«Старт» в диалоге: фиксируем пользователя; приветствие — только при
    AUTO_REPLY (консервация до переезда на хостинг, решение 11.11.2026)."""
    chat_id = update.get("chat_id")
    u = update.get("user") or {}
    owner_user_id = str(u.get("user_id") or "")
    if not owner_user_id or not isinstance(chat_id, int) or chat_id <= 0:
        return
    user = reg["users"].get(owner_user_id) or {
        "owner_user_id": int(owner_user_id),
        "owner_name": (u.get("name") or "").strip(),
    }
    user.setdefault("dialog_chat_id", chat_id)
    if not user.get("owner_name"):
        user["owner_name"] = (u.get("name") or "").strip()
    if user.get("state") == "stopped":
        user["state"] = "new"  # вернулся — снова ждём бриф
    reg["users"][owner_user_id] = user
    save_registry(reg)
    log_line("bot_started", f"owner={owner_user_id} chat={chat_id}")
    if AUTO_REPLY:
        send_dialog(token, chat_id, GREETING_TEXT)


def process_updates(token: str, updates: list[dict], reg: dict, seen_mids: set[str]) -> int:
    handled = 0
    for u in updates:
        record_churn(u)
        if u.get("update_type") == "bot_started":
            process_bot_started(token, reg, u)
            handled += 1
            continue
        if u.get("update_type") not in ("message_created", "message_edited"):
            continue
        m = u.get("message") or {}
        r = m.get("recipient") or {}
        if r.get("chat_type") != "dialog":
            continue  # RULE: реагируем только на личку (Ч-правило каналов)
        mid = str(((m.get("body") or {}).get("mid")) or "")
        if mid in seen_mids:
            continue
        sender = m.get("sender") or {}
        owner_user_id = str(sender.get("user_id") or "")
        user = reg["users"].get(owner_user_id)
        if user:
            user.setdefault("seen_mids", [])
            if mid in user["seen_mids"]:
                continue
        if user:
            user.setdefault("dialog_chat_id", r.get("chat_id"))
        else:
            # первый контакт: создаём пользователя в реестре до парсинга
            reg["users"][owner_user_id] = {
                "owner_user_id": int(owner_user_id),
                "owner_name": f"{sender.get('first_name', '')} {sender.get('last_name', '')}".strip(),
                "dialog_chat_id": r.get("chat_id"),
            }
        seen_mids.add(mid)
        process_message(token, reg, mid, sender, (m.get("body") or {}).get("text") or "")
        handled += 1
    return handled


def poll(timeout: int) -> int:
    token = load_token()
    reg = load_registry()
    seen = set()
    for u in reg["users"].values():
        seen.update(u.get("seen_mids") or [])

    marker = None
    if POLLSTATE_PATH.exists():
        marker = json.loads(POLLSTATE_PATH.read_text(encoding="utf-8")).get("marker")
    params = [f"timeout={timeout}"]
    if marker is not None:
        params.append(f"marker={int(marker)}")
    res = api_call(token, f"/updates?{'&'.join(params)}")
    if res["status"] != 200:
        log_line("poll_error", f"status={res['status']}")
        print(f"poll: HTTP {res['status']}")
        return 1
    data = res["json"] or {}
    new_marker = data.get("marker")
    if new_marker is not None:
        POLLSTATE_PATH.write_text(json.dumps({"marker": new_marker}), encoding="utf-8")
    handled = process_updates(token, data.get("updates") or [], reg, seen)
    print(f"poll: processed={handled}")
    return 0


# ---------- дайджест ----------

def _day_count(user: dict, today) -> int:
    stats = user.get("digests_today") or {}
    if stats.get("date") == today.isoformat():
        return int(stats.get("count") or 0)
    return 0


def is_due(user: dict) -> tuple[bool, str]:
    """Расписание MVP: daily — 1 дайджест в сутки; twice — 2 (утро и вечер);
    weekdays_only — только пн-пт. Часовые подсказки пока игнорируем.

    Счётчик отправок живёт в реестре (`digests_today`), а не выводится из
    `last_digest_at`: иначе при опросе каждые 5-10 минут «twice» уходил бы
    в бесконечную серию дайджестов в тот же день.
    """
    import datetime as dt
    today = dt.date.today()
    freq = user.get("frequency") or {}
    if today.weekday() >= 5 and freq.get("weekdays_only"):
        return False, "weekend (weekdays_only)"
    limit = 2 if freq.get("kind") == "twice" else 1
    count = _day_count(user, today)
    last = user.get("last_digest_at")
    if not last:
        return True, "never sent"
    try:
        last_dt = dt.datetime.fromisoformat(last)
    except ValueError:
        return True, "last_digest_at unreadable"
    if count == 0 and last_dt.date() == today:
        # реестр старого формата: отправка сегодня была, счётчика ещё нет
        count = 1
    if count < limit:
        return True, f"under daily limit {count}/{limit}"
    return False, f"daily limit reached {count}/{limit}"


def digest_run(dry: bool) -> int:
    import news_digest  # noqa: PLC0415 (локальный импорт модуля рядом)

    token = load_token()
    reg = load_registry()
    sent_any = 0
    for owner, user in (reg.get("users") or {}).items():
        if user.get("state") != "active":
            continue
        due, reason = is_due(user)
        if not dry and not due:
            print(f"  skip owner={owner} ({reason})")
            continue
        items = news_digest.collect(user)
        if not items:
            log_line("digest_empty", f"owner={owner} reason=no theme matches")
            print(f"  owner={owner}: no matching news")
            continue
        text = news_digest.assemble(items, user)
        if dry:
            out = LOCAL / f"digest_preview_{owner}.txt"
            out.write_text(text, encoding="utf-8")
            print(f"  owner={owner}: preview items={len(items)} chars={len(text)} -> {out.name}")
            continue
        status, mid = send_dialog(token, user.get("dialog_chat_id") or 0, text)
        if status == 200:
            sent_any += 1
            user["last_digest_at"] = datetime.datetime.now(
                datetime.timezone.utc).astimezone().isoformat(timespec="seconds")
            today_key = datetime.date.today().isoformat()
            stats = user.get("digests_today") or {}
            if stats.get("date") == today_key:
                stats["count"] = int(stats.get("count") or 0) + 1
            else:
                stats = {"date": today_key, "count": 1}
            user["digests_today"] = stats
            year_titles = [f"{i.get('pub','')[:15]}|{i['title']}" for i in items]
            titles = (user.get("sent_titles") or []) + year_titles
            user["sent_titles"] = titles[-60:]
            save_registry(reg)
            log_line("digest_sent", f"owner={owner} items={len(items)} mid={mid}")
            print(f"  owner={owner}: sent status={status}")
        else:
            log_line("digest_fail", f"owner={owner} status={status}")
            print(f"  owner={owner}: send FAILED status={status}")
    print(f"digest: sent={sent_any}")
    return 0


def registry_summary() -> int:
    reg = load_registry()
    users = reg.get("users") or {}
    active = [u for u in users.values() if u.get("state") == "active"]
    print(f"registry: users={len(users)} active={len(active)}")
    for owner, u in users.items():
        print(f"  owner={owner} state={u.get('state')} chat={u.get('dialog_chat_id')} "
              f"themes={u.get('themes')}")
    return 0


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "poll"
    if cmd == "poll":
        timeout = int(argv[2]) if len(argv) > 2 else 0
        return poll(timeout)
    if cmd == "registry":
        return registry_summary()
    if cmd == "digest":
        dry = "--dry" in (argv[2:] or [])
        return digest_run(dry)
    print("unknown command; use poll | digest [--dry] | registry")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
