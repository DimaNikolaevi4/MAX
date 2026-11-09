# -*- coding: utf-8 -*-
"""Проверка орфографии, пунктуации и грамматики русского текста.

Используется публикаторами перед отправкой поста. Проверка идёт через
публичный API LanguageTool (https://api.languagetool.org/v2/check).
Текст короткий (до 4000 символов), поэтому хватает одного запроса.

Классификация:
  * ошибки (errors) — орфография, опечатки, пунктуация, грамматика:
    публикацию блокируем;
  * замечания (warnings) — стиль, регистр, повторы и прочее:
    показываем, но не блокируем.

Если сервис недоступен, возвращается status="unavailable": публикатор
предупреждает и продолжает (проверка не должна ронять публикацию из-за сети).

CLI:
  python shared/text_check.py "Текст для проверки"
"""
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

LT_URL = "https://api.languagetool.org/v2/check"
ERROR_ISSUE_TYPES = {"misspelling", "typographical", "grammar", "punctuation"}
ERROR_CATEGORY_IDS = {"TYPOS", "PUNCTUATION", "GRAMMAR", "TYPOGRAPHY"}
# Короткие подписи канала пишутся со строчной буквы — это осознанный стиль.
ALLOWED_RULES = {"UPPERCASE_SENTENCE_START"}


def _post(text: str, language: str, timeout: int) -> tuple[str, int]:
    data = urllib.parse.urlencode({
        "text": text,
        "language": language,
        "enabledOnly": "false",
    }).encode("utf-8")
    req = urllib.request.Request(LT_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    ctx = ssl.create_default_context()
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace"), r.status
    except urllib.error.HTTPError as e:
        return e.read().decode("utf-8", errors="replace"), e.code
    except Exception as e:  # noqa: BLE001
        return f"transport error: {e!r}", 0


def _line_col(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    last_nl = text.rfind("\n", 0, offset)
    col = offset - last_nl
    return line, col


def _normalize(text: str, match: dict) -> dict:
    offset = int(match.get("offset", 0))
    length = int(match.get("length", 0))
    rule = match.get("rule") or {}
    issue_type = rule.get("issueType") or ""
    category = rule.get("category") or {}
    category_id = category.get("id") or ""
    rule_id = rule.get("id") or ""
    line, col = _line_col(text, offset)
    replacements = [r.get("value", "") for r in (match.get("replacements") or [])]
    is_error = (
        rule_id not in ALLOWED_RULES
        and (issue_type in ERROR_ISSUE_TYPES or category_id in ERROR_CATEGORY_IDS)
    )
    return {
        "offset": offset,
        "length": length,
        "line": line,
        "col": col,
        "fragment": text[offset:offset + length],
        "message": match.get("message") or rule.get("description") or "",
        "issue_type": issue_type,
        "rule_id": rule_id,
        "category": category.get("name") or "",
        "category_id": category_id,
        "replacements": replacements[:5],
        "is_error": is_error,
    }


def check_text(text: str, language: str = "ru-RU", timeout: int = 25,
               ignore_words=()) -> dict:
    """Возвращает {status, errors, warnings, ignored, message}.

    ignore_words — имена и авторские слова, которые проверка не должна
    считать ошибкой (например, клички животных).
    status: ok | errors | unavailable
    """
    text = (text or "").strip()
    if not text:
        return {"status": "ok", "errors": [], "warnings": [], "ignored": 0,
                "message": "пустой текст"}
    body, code = _post(text, language, timeout)
    if code != 200:
        return {"status": "unavailable", "errors": [], "warnings": [], "ignored": 0,
                "message": f"LanguageTool HTTP {code}: {body[:160]}"}
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return {"status": "unavailable", "errors": [], "warnings": [], "ignored": 0,
                "message": f"LanguageTool вернул не JSON: {body[:160]}"}
    ignored_set = {str(w).strip().lower() for w in ignore_words if str(w).strip()}

    def is_ignored(fragment: str) -> bool:
        frag = (fragment or "").strip().lower()
        if not frag:
            return False
        for word in ignored_set:
            if frag == word or frag in word or word in frag:
                return True
        return False

    issues = []
    ignored = 0
    for m in (data.get("matches") or []):
        issue = _normalize(text, m)
        if is_ignored(issue["fragment"]):
            ignored += 1
            continue
        issues.append(issue)
    errors = [i for i in issues if i["is_error"]]
    warnings = [i for i in issues if not i["is_error"]]
    return {
        "status": "errors" if errors else "ok",
        "errors": errors,
        "warnings": warnings,
        "ignored": ignored,
        "message": "ошибок нет" if not errors else f"ошибок: {len(errors)}",
    }


def format_issue(issue: dict) -> str:
    frag = issue["fragment"].replace("\n", " ")
    msg = issue["message"].strip()
    repl = ", ".join(issue["replacements"])
    tail = f" → {repl}" if repl else ""
    return (f"строка {issue['line']}, символ {issue['col']}: "
            f"«{frag}» — {msg}{tail}")


def main() -> None:
    text = " ".join(sys.argv[1:]).strip()
    if not text:
        raise SystemExit('Использование: python shared/text_check.py "Текст"')
    result = check_text(text)
    if result["status"] == "unavailable":
        print("ПРОВЕРКА НЕДОСТУПНА: " + result["message"])
        raise SystemExit(2)
    for issue in result["errors"]:
        print("ОШИБКА: " + format_issue(issue))
    for issue in result["warnings"]:
        print("ЗАМЕЧАНИЕ: " + format_issue(issue))
    print(result["message"])
    raise SystemExit(1 if result["errors"] else 0)


if __name__ == "__main__":
    main()
