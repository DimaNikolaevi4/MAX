# Самотест парсера брифа (офлайн, без API). Вывод ASCII-only.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from brief import FORM_HINT, is_stop, parse_brief  # noqa: E402

CASES = [
    {
        "name": "real_user_message",
        "text": "тест дайджеста, темы: ИИ, нейросети",
        "expect": {"ok": True, "themes": ["ИИ", "нейросети"], "kind": "daily", "warnings": []},
    },
    {
        "name": "full_form",
        "text": "темы: ИИ, нейросети, робототехника\nчастота: утром+вечером\nисточники: Habr, VC",
        "expect": {"ok": True, "themes": ["ИИ", "нейросети", "робототехника"], "sources": ["Habr", "VC"], "kind": "twice"},
    },
    {
        "name": "weekdays",
        "text": "Темы :医学, агентстве\nЧАСТОТА: только будни",
        "expect": {"ok": True, "kind": "daily", "weekdays_only": True},
    },
    {
        "name": "six_themes_capped",
        "text": "темы: a, b, c, d, e, f",
        "expect": {"ok": True, "warnings_present": True},
    },
    {
        "name": "unknown_frequency",
        "text": "темы: крипта\nчастота: когда новре",
        "expect": {"ok": True, "warnings_present": True, "kind": "daily"},
    },
    {
        "name": "evening_hint",
        "text": "темы: космос\nчастота: вечером",
        "expect": {"ok": True, "kind": "daily", "hour_hint": "evening"},
    },
    {
        "name": "no_themes",
        "text": "привет, сделай мне новости побыстрее",
        "expect": {"ok": False},
    },
    {
        "name": "nbsp_theme",
        "text": "темы:\u00a0ИИ,\u00a0LLM",
        "expect": {"ok": True, "themes": ["ИИ", "LLM"]},
    },
    {
        "name": "stop_plain",
        "text": "стоп",
        "stop": True,
    },
    {
        "name": "stop_with_noise",
        "text": "ВСЁ, стоп",
        "stop": False,
    },
]


def run_case(case: dict) -> tuple[bool, str]:
    if case.get("stop") is not None:
        got = is_stop(case["text"])
        ok = got == case["stop"]
        return ok, f"is_stop={got} (expected={case['stop']})"

    result = parse_brief(case["text"])
    ok, why = True, ""
    expect = case["expect"]

    if expect.get("ok") != result.get("ok"):
        return False, f"ok mismatch: got={result.get('ok')} detail={result}"
    if not expect.get("ok"):
        return True, "ok=False as expected"

    if "themes" in expect and result.get("themes") != expect["themes"]:
        return False, f"themes mismatch: got={result.get('themes')} want={expect['themes']}"
    if "sources" in expect and result.get("sources") != expect["sources"]:
        return False, f"sources mismatch: got={result.get('sources')} want={expect['sources']}"

    freq = result.get("frequency") or {}
    if "kind" in expect and freq.get("kind") != expect["kind"]:
        return False, f"frequency.kind mismatch: got={freq.get('kind')} want={expect['kind']}"
    if expect.get("weekdays_only"):
        if not freq.get("weekdays_only"):
            return False, "weekdays_only missing"
    if expect.get("hour_hint"):
        if freq.get("hour_hint") != expect["hour_hint"]:
            return False, f"hour_hint mismatch: got={freq.get('hour_hint')}"
    has_warn = bool(result.get("warnings"))
    if expect.get("warnings") is False and has_warn:
        return False, f"unexpected warnings: {result.get('warnings')}"
    if expect.get("warnings_present") and not has_warn:
        return False, "expected warnings, none present"
    return True, ""


def main() -> int:
    failures = 0
    for case in CASES:
        ok, detail = run_case(case)
        if not ok:
            failures += 1
        print(f"{'PASS' if ok else 'FAIL'}  {case['name']}" + (f"  | {detail}" if detail else ""))
    print("failures:", failures)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
