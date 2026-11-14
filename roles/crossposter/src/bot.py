# -*- coding: utf-8 -*-
"""Кросс Автопостинг (@se14808890_1_bot) — слушатель обновлений, этап 1.

Что делает (этап 1 «Старт + автоответ», до 21.11.2026):
  * long polling GET /updates (marker хранится в local/bot2-state.json);
  * bot_started            -> приветствие + inline-меню (кнопки);
  * message_callback       -> обработка кнопок меню (ответ + POST /answers);
  * message_created        -> простые автоответы по ключевым словам + fallback;
  * бот умеет писать пользователю первым (POST /messages в его диалог).

Запуск:  py roles\\crossposter\\src\\bot.py            (резидентно, Ctrl+C)
Токен:   local/tokens.json -> ключ "bot2" (заполняется bot2_register.py).
Логи:    local/logs/crossposter-bot.log (UTF-8) + строка в stdout.

Ограничения: 2 сообщения/сек на чат, 30 rps на API; между отправками пауза.
"""
import json
import os
import ssl
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

REPO = Path(r"E:\github\MAX")
STATE = REPO / "local" / "bot2-state.json"
LOGDIR = REPO / "local" / "logs"
LOCK = REPO / "local" / "bot2-listener.lock"

API = "https://platform-api2.max.ru"
UA = "curl/8.13.0"
POLL_TIMEOUT = 30          # сек long poll (0-90)
SEND_PAUSE = 1.2           # пауза между отправками (лимит 2/сек)


def make_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ca = REPO / "local" / "russian_ca_bundle.pem"
    if ca.exists():
        ctx.load_verify_locations(cafile=str(ca))
    return ctx


CTX = make_ctx()

# --- тексты этапа 1 ---------------------------------------------------------

WELCOME = (
    "Привет! Я **Кросс Автопостинг** — помощник авторов каналов MAX.\n\n"
    "Сейчас я на ранней стадии, но уже скоро научусь:\n"
    "✍️ вычитывать тексты перед публикацией\n"
    "⏰ публиковать посты по расписанию\n"
    "🔁 переносить посты из Telegram в MAX\n\n"
    "Нажмите кнопку ниже или напишите «возможности» — расскажу подробнее."
)

CAPABILITIES = (
    "**Что я умею и чему учусь**\n\n"
    "🟢 Сейчас:\n"
    "• знакомство и помощь с навигацией\n\n"
    "🔧 В разработке (дорожная карта, docs/bot2-roadmap.md):\n"
    "• этап 2 — вычитка текста: пришлёте черновик — верну исправленный вариант\n"
    "• этап 3–4 — анализ канала и подбор SEO-ядра\n"
    "• этап 5 — отложенный постинг по расписанию\n"
    "• этап 6 — кросспостинг Telegram ↔ MAX\n\n"
    "О новых этапах сообщу здесь же — бот умеет писать первым."
)

FALLBACK = (
    "Я пока учусь и понимаю только простые команды: «возможности», «старт», "
    "«помощь». Вычитка и постинг появятся скоро — напишите «возможности», "
    "чтобы посмотреть, что в разработке."
)

# callback payload -> ответ
MENU = {
    "menu.capabilities": CAPABILITIES,
    "menu.welcome": WELCOME,
}

# ключевые слова -> ответ (проверяются по lowercase-подстроке)
KEYWORDS = [
    (("возможност", "что умеешь", "умеешь"), CAPABILITIES),
    (("старт", "привет", "здравствуй", "начать"), WELCOME),
    (("помощь", "help"), CAPABILITIES),
]

BUTTONS = [
    [
        {"type": "callback", "text": "Возможности бота", "payload": "menu.capabilities"},
    ],
    [
        {"type": "callback", "text": "С начала", "payload": "menu.welcome"},
    ],
]


def log(msg: str) -> None:
    line = "%s | %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        LOGDIR.mkdir(parents=True, exist_ok=True)
        with open(LOGDIR / "crossposter-bot.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    return {}


def save_state(state: dict) -> None:
    STATE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def api(token: str, method: str, path: str, payload: dict | None = None):
    url = API + path
    data = None
    headers = {"Authorization": token, "User-Agent": UA}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=POLL_TIMEOUT + 10) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001
            return e.code, {}
    except Exception as e:  # noqa: BLE001
        log("NET: %s %s -> %r" % (method, path, e))
        return None, {}


def send_text(token: str, chat_id: int, text: str) -> bool:
    payload = {"text": text, "format": "markdown",
               "attachments": [{"type": "inline_keyboard",
                                 "payload": {"buttons": BUTTONS}}]}
    code, resp = api(token, "POST", "/messages?chat_id=%d" % chat_id, payload)
    ok = code == 200 and (resp or {}).get("success") is not False
    if not ok:
        log("SEND FAIL chat=%s code=%s resp=%s" % (chat_id, code, str(resp)[:200]))
    time.sleep(SEND_PAUSE)
    return ok


def answer_callback(token: str, callback_id: str, text: str) -> None:
    code, resp = api(token, "POST", "/answers", {
        "callback_id": callback_id,
        "message": {"text": text, "format": "markdown"},
    })
    if code != 200:
        log("ANSWER FAIL id=%s code=%s resp=%s" % (callback_id, code, str(resp)[:200]))
    time.sleep(SEND_PAUSE)


def user_dialog_chat_id(update: dict) -> int | None:
    """chat_id диалога пользователя с ботом — положительный, = user_id."""
    message = update.get("message") or {}
    sender = message.get("sender") or {}
    uid = sender.get("user_id")
    if uid is not None:
        return uid
    return update.get("chat_id")


def handle(token: str, upd: dict) -> None:
    utype = upd.get("update_type")
    chat_id = upd.get("chat_id")
    if utype == "bot_started":
        who = ((upd.get("user") or {}).get("first_name")) or ""
        log("bot_started chat=%s user=%r" % (chat_id, who))
        send_text(token, chat_id, WELCOME)
    elif utype == "message_callback":
        payload = (upd.get("callback") or {}).get("payload")
        callback_id = (upd.get("callback") or {}).get("callback_id")
        log("message_callback chat=%s payload=%r" % (chat_id, payload))
        text = MENU.get(payload)
        if text and callback_id:
            answer_callback(token, callback_id, "Открываю…")
            send_text(token, chat_id, text)
    elif utype == "message_created":
        body = (upd.get("message") or {}).get("body") or {}
        text = (body.get("text") or "").strip().lower()
        sender = ((upd.get("message") or {}).get("sender") or {}).get("first_name") or ""
        log("message_created chat=%s from=%r text=%r" % (chat_id, sender, text[:60]))
        if not text:
            return
        dlg = user_dialog_chat_id(upd)
        if dlg is None:
            return
        reply = None
        for needles, response in KEYWORDS:
            if any(n in text for n in needles):
                reply = response
                break
        send_text(token, dlg, reply or FALLBACK)
    elif utype in ("bot_stopped", "dialog_removed"):
        log("%s chat=%s" % (utype, chat_id))


def main() -> None:
    if LOCK.exists():
        log("FAIL: слушатель уже запущен (lock: %s)" % LOCK)
        raise SystemExit(2)
    LOCK.write_text(str(os.getpid()), encoding="utf-8")
    try:
        creds = json.loads((REPO / "local" / "tokens.json").read_text(encoding="utf-8"))
        token = (creds.get("bot2") or {}).get("token")
        if not token:
            log("FAIL: в local/tokens.json нет ключа bot2 (запустите "
                "local/bot2_register.py после записи токена в bot2-token.txt)")
            raise SystemExit(3)

        code, me = api(token, "GET", "/me")
        if code != 200 or not (me or {}).get("is_bot"):
            log("FAIL: GET /me вернул %s %s" % (code, str(me)[:200]))
            raise SystemExit(3)
        log("старт: бот %r (@%s) user_id=%s" % (
            me.get("name"), me.get("username"), me.get("user_id")))

        state = load_state()
        marker = state.get("marker")
        log("marker: %s" % marker)
        while True:
            path = "/updates?timeout=%d&types=bot_started&types=message_callback" \
                   "&types=message_created&types=bot_stopped&types=dialog_removed" % POLL_TIMEOUT
            if marker is not None:
                path += "&marker=%d" % marker
            code, data = api(token, "GET", path)
            if code != 200 or not isinstance(data, dict):
                time.sleep(5)
                continue
            marker = data.get("marker")
            if marker is not None:
                state["marker"] = marker
                save_state(state)
            for upd in data.get("updates") or []:
                try:
                    handle(token, upd)
                except Exception as e:  # noqa: BLE001
                    log("HANDLE ERR: %r (upd=%s)" % (e, str(upd)[:200]))
    finally:
        try:
            LOCK.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("остановлен вручную")
