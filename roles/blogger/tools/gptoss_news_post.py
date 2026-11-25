# -*- coding: utf-8 -*-
"""Дневной пост ainow через Cloudflare Workers AI (@cf/openai/gpt-oss-120b).

Использование (из корня E:\\github\\MAX):
  py roles\\blogger\\tools\\gptoss_news_post.py --news local\\gptoss-news\\<дата>-news.json \
      --out local\\gptoss-news\\<дата>-raw.txt

Токен и account_id читаются из gitignored local/cf_config.json, а при его отсутствии
из E:\\github\\ai.txt (строки `cfut_…` и URL dash.cloudflare.com/<account_id>/…).
Ни токен, ни account_id не попадают в аргументы, логи и выходные файлы.
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PROMPT = REPO / "roles/blogger/channels/ainow/gptoss-news-prompt.md"
CRED = REPO / "local/cf_config.json"
AI_FILE = Path(r"E:\github\ai.txt")
MODEL = "@cf/openai/gpt-oss-120b"
DECISION_MARK = "---DECISION---"


def credentials() -> dict:
    if CRED.is_file():
        cfg = json.loads(CRED.read_text(encoding="utf-8"))
        if cfg.get("token") and cfg.get("account_id"):
            return cfg
    if not AI_FILE.is_file():
        raise SystemExit("нет токена: ни local/cf_config.json, ни E:\\github\\ai.txt")
    lines = AI_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    token = next((l.strip() for l in lines if l.strip().startswith("cfut_")), None)
    account = None
    for line in lines:
        m = re.search(r"dash\.cloudflare\.com/([0-9a-f]{24,40})/", line)
        if m:
            account = m.group(1)
            break
    if not (token and account):
        raise SystemExit("в E:\\github\\ai.txt не найдены токен и account_id")
    cfg = {"account_id": account, "token": token}
    CRED.parent.mkdir(parents=True, exist_ok=True)
    CRED.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg


def build_prompt(news: dict) -> tuple[str, str]:
    raw = PROMPT.read_text(encoding="utf-8")
    raw = raw.split("---\n\nSYSTEM:", 1)[1] if "---\n\nSYSTEM:" in raw else raw
    sys_text, user_text = raw.split("\nUSER:\n", 1)
    sys_text = sys_text.strip()
    user_text = user_text.strip()

    facts = news.get("facts") or []
    facts_text = "\n".join(f"— {f}" for f in facts) if facts else "— нет данных"
    links = news.get("context_links") or []
    links_text = "\n".join(
        f"— [{x['anchor']}]({x['url']})" for x in links) if links else "— нет"
    disc = news.get("discussion") or {}
    disc_text = (f"{disc.get('comments', '?')} комментариев, "
                 f"источник сигнала: {disc.get('where', 'не указано')}")

    subs = {
        "{{DATE}}": news.get("checked_at", ""),
        "{{TITLE}}": news.get("title", ""),
        "{{SOURCE}}": news.get("source", ""),
        "{{URL}}": news.get("url", ""),
        "{{PUBLISHED_AT}}": news.get("published_at", ""),
        "{{DISCUSSION}}": disc_text,
        "{{FACTS}}": facts_text,
        "{{CONTEXT_LINKS}}": links_text,
    }
    for k, v in subs.items():
        user_text = user_text.replace(k, str(v))
    return sys_text, user_text


def main() -> None:
    global PROMPT
    ap = argparse.ArgumentParser()
    ap.add_argument("--news", required=True, help="JSON с проверенной новостью")
    ap.add_argument("--out", required=True, help="куда сохранить сырой текст поста")
    ap.add_argument("--prompt", default=str(PROMPT))
    args = ap.parse_args()

    news_path = Path(args.news)
    if not news_path.is_absolute():
        news_path = REPO / news_path
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = REPO / out_path
    news = json.loads(news_path.read_text(encoding="utf-8"))

    prompt_path = Path(args.prompt)
    PROMPT = prompt_path
    sys_text, user_text = build_prompt(news)

    cfg = credentials()
    url = ("https://api.cloudflare.com/client/v4/accounts/" + cfg["account_id"] +
           "/ai/run/" + MODEL)
    payload = {
        "messages": [
            {"role": "system", "content": sys_text},
            {"role": "user", "content": user_text},
        ],
        "max_tokens": 3500,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": "Bearer " + cfg["token"],
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        err = REPO / "local/gptoss-news/last-error.txt"
        err.parent.mkdir(parents=True, exist_ok=True)
        err.write_text(e.read().decode("utf-8", "replace"), encoding="utf-8")
        raise SystemExit(f"HTTP {e.code}, detail: {err.relative_to(REPO)}")
    except Exception as e:
        raise SystemExit(f"ERR {type(e).__name__}: {str(e)[:300]}")

    result = data.get("result") or {}
    choices = result.get("choices") or []
    if choices:
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        if isinstance(content, list):
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        answer = content or ""
    else:
        answer = result.get("response") or ""

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(answer, encoding="utf-8")
    if DECISION_MARK in answer:
        post, decision = answer.split(DECISION_MARK, 1)
        out_path.with_name(out_path.stem + "-decision.txt").write_text(
            decision.strip(), encoding="utf-8")
    else:
        post = answer

    usage = result.get("usage") or {}
    print("HTTP 200 | model:", MODEL,
          "| chars:", len(post.strip()),
          "| tokens:", usage.get("total_tokens"),
          "| neurons:", usage.get("neurons"))


if __name__ == "__main__":
    main()
