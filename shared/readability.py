# -*- coding: utf-8 -*-
"""Эвристики читаемости русского текста (только флаги, без автоправки).

Введено 11.11.2026 после ручной правки выпуска №2: «поставщики памяти
двигают цены» → «поставщики памяти и двигают цены». Такие блоки грамматически
корректны (LanguageTool их не ловит), но плохо читаются; часть ловится
детерминированными эвристиками.

Принципы:
  * только WARN — эвристика может ошибаться, публикацию не блокирует;
  * на входе — «человеческий» текст (см. plain_text() публикатора),
    без markdown-разметки;
  * морфологии нет: эвристики грубые, поэтому лучше лишний WARN, чем пропуск.

Эвристики (пороги подобраны на выпусках na100):
  1. длинное предложение — > 30 слов;
  2. перечисление без союза — 3+ запятые в предложении и ни одного
     « и » / « или » между ними: вероятно пропущен союз при однородных;
  3. повтор слова в предложении — то же слово (5+ букв, не служебное)
     встречается 2+ раза;
  4. канцелярит — фразы из BUREAUCRATIC (детектор, не автозамена);
  5. пробелы и пунктуация — двойные пробелы, пробел перед запятой/точкой,
     нет пробела после запятой;
  6. непарные кавычки/скобки — « » и ( ).

CLI:
  python shared/readability.py <файл-с-текстом.txt>
"""
import re
import sys
from pathlib import Path

MAX_WORDS = 30          # слов в предложении
REPEAT_MIN_LEN = 5      # минимальная длина слова для повтора
MIN_COMAS = 3           # запятых в предложении для эвристики перечисления

# канцелярит: детектор, НЕ автозамена (замену выбирает вычитка)
BUREAUCRATIC = [
    "является", "являются", "являлся", "являлась",
    "осуществляет", "осуществление", "осуществляться", "осуществили",
    "данный", "данная", "данное", "данного", "данной",
    "в рамках", "в целях", "с целью", "в связи с этим",
    "необходимо отметить", "следует отметить", "стоит отметить",
    "имеет место", "в настоящее время", "по итогам",
    "проведени",  # «после проведения модернизации» — выпуск №2, не ловился
    "осуществ",
]

# служебные и «легальные» повторы (не флагируем)
REPEAT_ALLOWED = {
    "чтобы", "которые", "который", "которая", "которое", "когда", "если",
    "потому", "тогда", "тоже", "также", "почти", "можно", "нужно",
    "пока", "снова", "более", "очень",
}

SENT_RE = re.compile(r"[^.!?\n]+[.!?]+|[^.!?\n]+$")
WORD_RE = re.compile(r"[а-яёa-z]+", re.I)


def _iter_sentences(text: str):
    for m in SENT_RE.finditer(text):
        s = m.group(0).strip()
        if len(WORD_RE.findall(s)) >= 3:
            yield m.start(), s


def check_readability(text: str) -> list[dict]:
    """Вернуть список замечаний {line, col, fragment, message, rule}."""
    issues = []
    text = (text or "").strip()
    if not text:
        return issues

    for off, sent in _iter_sentences(text):
        words = WORD_RE.findall(sent)

        # 1. длинное предложение
        if len(words) > MAX_WORDS:
            issues.append({
                "line": text[:off].count("\n") + 1,
                "col": 1,
                "fragment": sent[:80] + ("…" if len(sent) > 80 else ""),
                "message": (f"длинное предложение: {len(words)} слов "
                            f"(порог {MAX_WORDS}) — разбить или упростить"),
                "rule": "long_sentence",
            })

        # 2. перечисление без союза
        if sent.count(",") >= MIN_COMAS and not re.search(r"\s(и|или)\s", sent, re.I):
            issues.append({
                "line": text[:off].count("\n") + 1,
                "col": 1,
                "fragment": sent[:80] + ("…" if len(sent) > 80 else ""),
                "message": ("много однородных членов без союза «и»/«или» — "
                            "вероятно пропущен союз (споткнётся чтение)"),
                "rule": "list_without_union",
            })

        # 3. повтор слова в предложении
        seen = {}
        for w in words:
            lw = w.lower()
            if len(lw) < REPEAT_MIN_LEN or lw in REPEAT_ALLOWED:
                continue
            seen[lw] = seen.get(lw, 0) + 1
        for w, cnt in seen.items():
            if cnt >= 2:
                issues.append({
                    "line": text[:off].count("\n") + 1,
                    "col": 1,
                    "fragment": sent[:80] + ("…" if len(sent) > 80 else ""),
                    "message": f"повтор слова «{w}» ({cnt} раза в предложении)",
                    "rule": "word_repeat",
                })

    # 4. канцелярит
    for phrase in BUREAUCRATIC:
        for m in re.finditer(re.escape(phrase), text, re.I):
            issues.append({
                "line": text[:m.start()].count("\n") + 1,
                "col": m.start() - text.rfind("\n", 0, m.start()),
                "fragment": m.group(0),
                "message": "канцелярит — переформулировать «по-домашнему»",
                "rule": "bureaucratic",
            })

    # 5. пробелы и пунктуация
    for m in re.finditer(r"  +", text):
        issues.append({
            "line": text[:m.start()].count("\n") + 1,
            "col": m.start() - text.rfind("\n", 0, m.start()),
            "fragment": repr(m.group(0)),
            "message": "двойной пробел",
            "rule": "double_space",
        })
    for m in re.finditer(r"\s+[,;.](?!\.)", text):
        issues.append({
            "line": text[:m.start()].count("\n") + 1,
            "col": m.start() - text.rfind("\n", 0, m.start()),
            "fragment": text[max(0, m.start() - 12):m.end() + 12],
            "message": "пробел перед знаком препинания",
            "rule": "space_before_punct",
        })
    for m in re.finditer(r",[а-яёА-ЯЁ]", text):
        issues.append({
            "line": text[:m.start()].count("\n") + 1,
            "col": m.start() - text.rfind("\n", 0, m.start()),
            "fragment": text[max(0, m.start() - 12):m.end() + 12],
            "message": "нет пробела после запятой",
            "rule": "no_space_after_coma",
        })

    # 6. непарные кавычки/скобки (по абзацам)
    for para in re.split(r"\n{2,}", text):
        if para.count("«") != para.count("»"):
            issues.append({
                "line": text[:text.find(para)].count("\n") + 1 if text.find(para) >= 0 else 1,
                "col": 1,
                "fragment": para[:60] + ("…" if len(para) > 60 else ""),
                "message": "непарные кавычки « »",
                "rule": "unbalanced_quotes",
            })
        if para.count("(") != para.count(")"):
            issues.append({
                "line": text[:text.find(para)].count("\n") + 1 if text.find(para) >= 0 else 1,
                "col": 1,
                "fragment": para[:60] + ("…" if len(para) > 60 else ""),
                "message": "непарные скобки ( )",
                "rule": "unbalanced_parens",
            })

    return issues


def format_issue(issue: dict) -> str:
    frag = issue["fragment"].replace("\n", " ")
    return f"строка {issue['line']}: «{frag}» — {issue['message']}"


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Использование: python shared/readability.py <файл.txt>")
    text = Path(sys.argv[1]).read_text(encoding="utf-8")
    issues = check_readability(text)
    if not issues:
        print("читаемость: замечаний нет")
        return
    for i in issues:
        print("WARN: " + format_issue(i))
    print(f"читаемость: замечаний {len(issues)}")


if __name__ == "__main__":
    main()
