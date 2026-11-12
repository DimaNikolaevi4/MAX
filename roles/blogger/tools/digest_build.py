# -*- coding: utf-8 -*-
"""Детерминированная сборка выпуска na100 — задача Планировщика 06:30 МСК.

Разделение труда (решение 10.11.2026, docs/na100-relaunch-2026-11-10.md §6.2):
  * скрипт — сбор RSS, фильтр, скоринг, дедупликация, черновик-шортлист,
    обложка для готового поста, проверка готовности к публикации;
  * текст выпуска пишет агент в рабочей сессии по черновику
    (LLM в пайплайн не подключается — решение владельца 11.11.2026).

Что делает за запуск:
  1. Тянет RSS (config/techdigest_feeds.json, status ok/flaky), записи за
     последние 36 часов → local/digest/raw-<дата>.json (runtime, в git не идёт).
  2. Фильтрует: общий тех-словарь (кл. слова + игроки из major_players.json),
     стоп-лист exclude_topics (stop_list.json).
  3. Дедуплицирует сюжеты между фидами (Жаккар токенов заголовка ≥ 0.6),
     берёт лучшую версию, источники объединяет; размер подхвата (число
     фидов) — сигнал влияния №5.
  4. Скоринг: свежесть×0.3 + влияние×0.4 + новизна×0.2 + авторитет×0.1
     (0–10, порог 5.0; сигналы влияния — бинарный чек-лист, авторитет —
     таблица доменов). Память новизны — local/digest/last_7_days.json.
  5. Пишет черновик для агента channels/<канал>/digests/<дата>-draft.json
     (В РЕПОЗИТОРИИ — синхронизируется на все машины, решение владельца
     12.11.2026): кандидаты по
     регионам с разбором баллов + предложенный отбор (1 РФ + 1 Китай + 3 мира;
     пустой Китай → 1 РФ + 4 мира с пометкой).
  6. Обложка: если для сегодня есть approved-пост na100 без действующего
     image_file/video — фон из пула (pick_fallback.py) + digest_cover_photo.py
     (пункты панели — заголовки 1️⃣–5️⃣ в порядке поста); front matter
     дописывается, коммит и пуш.
  7. Проверка готовности: publish_scheduled.py --channel na100 --dry-run.

Отчёт — local/digest-build.txt; лог — local/logs/digest-build-na100.console.log
(пишет обёртка digest_build_na100.ps1).

Ручной запуск:
  py roles\\blogger\\tools\\digest_build.py --channel na100
"""
import argparse
import json
import re
import ssl
import subprocess
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
MSK = timezone(timedelta(hours=3))
FEEDS_CFG = REPO / "roles" / "blogger" / "config" / "techdigest_feeds.json"
MAJOR_CFG = REPO / "roles" / "blogger" / "config" / "major_players.json"
STOP_CFG = REPO / "roles" / "blogger" / "config" / "stop_list.json"
DIGEST = REPO / "local" / "digest"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) digest_build/0.2"
CUTOFF_HOURS = 36
THRESHOLD = 5.0
DEDUP_JACCARD = 0.6
MEMORY_KEEP_DAYS = 7

# тех-словарь: подстроки/стемы (проверяются по нормализованному заголовку);
# латиница — по границам слов
TECH_STEMS = [
    "нейросет", "искусственн", "чип", "процессор", "видеокарт", "полупроводник",
    "сервер", "дата-центр", "датацентр", "робот", "дрон", "беспилотн", "спутник",
    "ракет", "космос", "орбит", "телеком", "батарей", "аккумулятор",
    "электромобил", "смартфон", "ноутбук", "планшет", "наушник", "гаджет",
    "приложен", "операционн", "монитор", "клавиатур", "микросхем", "литограф",
    "складчин", "компьютер", "хакер", "утечк", "кибербезопасн", "роутер",
    "модем", "интернет", "браузер", "поисковик", "мессенджер", "соцсет",
    "умные часы", "умный дом", "фабрик", "гарнитур", "нацпроект", "минцифры",
    "реестр российского", "импортозамещ", "отечествен",
]
TECH_WORDS = [
    "ии", "ai", "gpu", "cpu", "5g", "6g", "ev", "vr", "ar", "x86", "os",
    "iot", "nft", "llm", "gpt", "rtx", "ryzen", "geforce", "radeon",
    "android", "windows", "linux", "iphone", "pixel", "galaxy", "titan",
]
STOP_TOKENS = {
    "для", "что", "это", "как", "уже", "ещё", "при", "от", "по", "на", "из",
    "за", "до", "его", "их", "она", "она", "обо", "или", "соб", "всех", "весь",
    "the", "a", "of", "to", "in", "for", "on", "with", "and", "is", "are",
    "new", "at", "by", "as", "it", "its", "be", "was",
}
AUTHORITY = {
    "techcrunch.com": 8, "theverge.com": 8, "tomshardware.com": 8,
    "scmp.com": 8, "spectrum.ieee.org": 9, "habr.com": 7, "opennet.ru": 7,
    "technode.com": 7, "phys.org": 7, "techradar.com": 6, "cnews.ru": 6,
    "venturebeat.com": 6, "globaltimes.cn": 5,
}
GOVERNMENT = [
    "сша", "китай", "китая", "китае", "россия", "россии", "российск",
    "евросоюз", "минцифры", "госдеп", "белый дом", "конгресс", "парламент",
    "еврокомисс", "ефс", "fcc",
]
PRICE_REG_STEMS = [
    "цен", "подорожа", "подешеве", "дорожа", "дешев", "запрет", "запрещ",
    "штраф", "санкц", "ограничен", "регул", "закон", "пошлин", "взлом",
    "утечк", "отзыв", "подписк", "price", "ban", "lawsuit", "regulat",
    "restrict", "breach", "hack", "leak", "fine", "tariff",
]
LAUNCH_STEMS = [
    "анонс", "представил", "запустил", "выпустил", "объявил", "релиз",
    "показал", "заявил", "впервые", "первый", "первая", "первое", "стартовал",
    "launch", "announc", "releas", "unveil", "debut", "rollout",
]
RUS_COMPANY = {"yandex": "яндекс", "sber": "сбер", "vk": "вконтакте"}

REPORT = DIGEST / "digest-build.txt"
LINES = []


def say(line=""):
    LINES.append(line)
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"))


def flush():
    DIGEST.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(LINES) + "\n", encoding="utf-8")


def norm(s: str) -> str:
    return " ".join(re.findall(r"[а-яёa-z0-9]+", (s or "").lower()))


def tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[а-яёa-z0-9]+", (s or "").lower())
            if len(t) >= 3 and t not in STOP_TOKENS}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def parse_date(s: str):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return parsedate_to_datetime(s).astimezone(MSK)
    except (ValueError, TypeError):
        pass
    try:
        return datetime.fromisoformat(re.sub(r"Z$", "+00:00", s)).astimezone(MSK)
    except ValueError:
        return None


def get_items(url: str) -> list[dict]:
    ctx = ssl.create_default_context()
    ca = REPO / "local" / "russian_ca_bundle.pem"
    if ca.exists():
        ctx.load_verify_locations(cafile=str(ca))
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, context=ctx, timeout=45) as r:
        body = r.read()
    root = ET.fromstring(body)
    local = lambda t: t.rsplit("}", 1)[-1].lower()  # noqa: E731
    items = []
    for it in root.iter():
        if local(it.tag) != "item" and local(it.tag) != "entry":
            continue
        title = link = None
        date_s = ""
        for ch in it:
            t = local(ch.tag)
            if t == "title" and ch.text:
                title = ch.text.strip()
            elif t == "link":
                # RSS 2.0: <link>url</link>; Atom: <link href="..."/>
                href = ch.get("href")
                if href and (link is None or "rel" not in ch.attrib):
                    link = href
                elif (ch.text or "").strip() and link is None:
                    link = ch.text.strip()
            elif t in ("pubdate", "dc:date", "published", "updated"):
                date_s = ch.text or ""
        if title:
            items.append({"title": title, "link": (link or "").strip(),
                          "date": date_s})
    return items


def fetch_feeds() -> dict:
    cfg = json.loads(FEEDS_CFG.read_text(encoding="utf-8"))
    now = datetime.now(MSK)
    cutoff = now - timedelta(hours=CUTOFF_HOURS)
    out = {}
    for feed in cfg["feeds"]:
        if feed.get("status") not in ("ok", "flaky"):
            continue
        try:
            raw = get_items(feed["url"])
        except Exception as exc:  # noqa: BLE001
            out[feed["name"]] = {"region": feed["region"],
                                 "error": str(exc)[:160], "items": []}
            say(f"фид FAIL: {feed['name']}: {str(exc)[:80]}")
            continue
        kept = []
        for it in raw:
            d = parse_date(it["date"])
            if d and d < cutoff:
                continue
            kept.append({"title": it["title"], "link": it["link"],
                         "dt": (d.isoformat() if d else it["date"]),
                         "ts": d.isoformat() if d else ""})
        out[feed["name"]] = {"region": feed["region"], "total": len(raw),
                             "items": kept[:60]}
        say(f"фид ok: {feed['name']}: {len(raw)} всего, свежих {len(kept)}")
        time.sleep(0.4)
    return out


def load_stop_and_players():
    major = json.loads(MAJOR_CFG.read_text(encoding="utf-8"))
    stop = json.loads(STOP_CFG.read_text(encoding="utf-8"))
    return major, stop


def tech_match(title: str, company_re) -> bool:
    t = norm(title)
    for stem in TECH_STEMS:
        if stem in t:
            return True
    for w in TECH_WORDS:
        if re.search(rf"\b{re.escape(w)}\b", t):
            return True
    return bool(company_re.search(t))


def excluded_by_stop(title: str, exclude_topics: list[str]) -> str | None:
    t = norm(title)
    for topic in exclude_topics:
        parts = [p for p in norm(topic).split()
                 if len(p) >= 4 or p in ("ставки",)]
        if not parts:
            continue
        if all(p in t for p in parts):
            return topic
    return None


def freshness_score(dt_str: str) -> tuple[int, float]:
    d = parse_date(dt_str)
    if not d:
        return 4, 99.0
    h = (datetime.now(MSK) - d).total_seconds() / 3600
    if h <= 4:
        return 10, h
    if h <= 12:
        return 8, h
    if h <= 24:
        return 6, h
    return 4, h


def influence_score(title: str, feed_count: int, company_re) -> tuple[int, list[str]]:
    t = norm(title)
    signals = []
    gov_or_co = bool(company_re.search(t)) or any(g in t for g in GOVERNMENT)
    if gov_or_co:
        signals.append("игрок/государство")
    if any(s in t for s in PRICE_REG_STEMS):
        signals.append("цена/регулирование/доступность")
    if any(s in t for s in LAUNCH_STEMS):
        signals.append("анонс/первый запуск")
    if feed_count >= 3:
        signals.append(f"подхват x{feed_count} изданий")
    # 4-й сигнал чек-листа («официальный анонс, а не слух») не отличим по
    # заголовку от сигнала запуска — решает агент по источнику
    return min(len(signals) * 2, 10), signals


def novelty_score(title: str, memory_tokens: list[set]) -> int:
    tt = tokens(title)
    best = max((jaccard(tt, mt) for mt in memory_tokens), default=0.0)
    if best >= DEDUP_JACCARD:
        return 2
    if best >= 0.4:
        return 6
    return 10


def dedup_clusters(records: list[dict]) -> list[list[dict]]:
    clusters: list[list[dict]] = []
    for r in records:
        rt = tokens(r["title"])
        merged = False
        for cl in clusters:
            if jaccard(rt, tokens(cl[0]["title"])) >= DEDUP_JACCARD:
                cl.append(r)
                merged = True
                break
        if not merged:
            clusters.append([r])
    return clusters


def score_clusters(clusters, memory_tokens, company_re, stop_topics) -> list[dict]:
    out = []
    for cl in clusters:
        feeds = sorted({r["feed"] for r in cl})
        best = max(cl, key=lambda r: freshness_score(r["dt"])[0])
        fresh, hours = freshness_score(best["dt"])
        infl, signals = influence_score(best["title"], len(feeds), company_re)
        nov = novelty_score(best["title"], memory_tokens)
        auth = max((AUTHORITY.get(_domain(r["link"]), 6) for r in cl), default=6)
        total = round(fresh * 0.3 + infl * 0.4 + nov * 0.2 + auth * 0.1, 2)
        if excluded_by_stop(best["title"], stop_topics):
            continue
        out.append({
            "title": best["title"], "link": best["link"], "dt": best["dt"],
            "region": cl[0]["region"], "feeds": feeds, "hours": round(hours, 1),
            "fresh": fresh, "influence": infl, "novelty": nov, "authority": auth,
            "total": total, "signals": signals, "sources": [
                r["link"] for r in cl if r["link"]][:6],
        })
    out.sort(key=lambda x: -x["total"])
    return out


def _domain(link: str) -> str:
    m = re.match(r"https?://([^/]+)", link or "")
    d = (m.group(1) if m else "").lower()
    return ".".join(d.split(".")[-2:]) if d else ""


def load_memory() -> list[set]:
    mem = DIGEST / "last_7_days.json"
    if not mem.exists():
        return []
    try:
        data = json.loads(mem.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return [tokens(t) for ts in data.get("entries", {}).values() for t in ts]


def update_memory(proposed: list[dict]):
    mem = DIGEST / "last_7_days.json"
    data = json.loads(mem.read_text(encoding="utf-8")) if mem.exists() else {}
    entries = data.get("entries", {})
    today = datetime.now(MSK).strftime("%Y-%m-%d")
    keep_date = (datetime.now(MSK) - timedelta(days=MEMORY_KEEP_DAYS)).date()
    entries = {d: v for d, v in entries.items()
               if datetime.strptime(d, "%Y-%m-%d").date() >= keep_date}
    titles = [n["title"] for n in proposed]
    entries[today] = titles
    data["entries"] = entries
    mem.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                   encoding="utf-8")


def build_draft(raw: dict, date: str) -> dict:
    major, stop = load_stop_and_players()
    companies = list(major.get("companies", []))
    for lat, rus in RUS_COMPANY.items():
        companies.append(rus)
    parts = []
    for c in companies:
        if re.search(r"[а-яё]", c):
            parts.append(re.escape(c))
        else:
            parts.append(rf"\b{re.escape(c.lower())}\b")
    company_re = re.compile("|".join(parts), re.I) if parts else re.compile(r"$^")

    memory_tokens = load_memory()
    records, dropped = [], []
    for feed_name, fd in raw.items():
        for it in fd.get("items") or []:
            r = {"feed": feed_name, "region": fd["region"],
                 "title": it["title"], "link": it["link"], "dt": it["dt"]}
            topic = excluded_by_stop(it["title"], stop.get("exclude_topics", []))
            if topic:
                dropped.append({"title": it["title"], "reason": f"стоп-лист: {topic}"})
                continue
            if not tech_match(it["title"], company_re):
                dropped.append({"title": it["title"], "reason": "не тех-тема"})
                continue
            records.append(r)

    clusters = dedup_clusters(records)
    scored = score_clusters(clusters, memory_tokens, company_re,
                            stop.get("exclude_topics", []))
    by_region = {}
    for s in scored:
        if s["total"] < THRESHOLD:
            continue
        by_region.setdefault(s["region"], []).append(s)

    ru = by_region.get("ru", [])[:1]
    cn = by_region.get("cn", [])[:1]
    world = by_region.get("world", [])[:4 if not cn else 3]
    proposed = ru + cn + world
    notes = []
    if not cn:
        notes.append("в китайском сегменте тихо — 1 РФ + 4 мира")
    if not ru:
        notes.append("нет кандидатов из РФ — состав уточняет агент")

    draft = {
        "date": date,
        "generated_at": datetime.now(MSK).isoformat(),
        "formula": "свежесть*0.3 + влияние*0.4 + новизна*0.2 + авторитет*0.1 "
                   f"(0-10, порог {THRESHOLD}); шаг 4 — обложка/текст у агента",
        "notes": notes,
        "proposed": proposed,
        "candidates": {"ru": by_region.get("ru", [])[:15],
                       "cn": by_region.get("cn", [])[:15],
                       "world": by_region.get("world", [])[:30]},
        "dropped": {"count": len(dropped),
                    "examples": [d for d in dropped[:12]]},
        "feeds_ok": [n for n, fd in raw.items()
                     if (fd.get("items") or fd.get("total"))],
        "feeds_fail": [n for n, fd in raw.items()
                       if fd.get("error") and not fd.get("items")],
    }
    update_memory(proposed)
    return draft


# --- обложка -------------------------------------------------------------

def numbered_items(body: str) -> list[str]:
    items = []
    for ln in body.splitlines():
        m = re.match(r"^\s*\d(?:\ufe0f\u20e3)?\s*\*\*(.+?)\*\*\s*$", ln.strip())
        if m:
            items.append(m.group(1).strip())
        if len(items) == 5:
            break
    return items


def find_approved_without_cover(channel: str) -> list[tuple[Path, dict, str]]:
    """approved-посты на сегодня без действующего медиа (как в publish_scheduled)."""
    from shared.paths import CONFIG  # noqa: E402
    posts_dir = REPO / "roles" / "blogger" / "channels" / channel / "posts"
    now = datetime.now(MSK).date()
    out = []
    for path in sorted(posts_dir.glob("*.md")):
        d = re.match(r"^(\d{4}-\d{2}-\d{2})-", path.name)
        if not d:
            continue
        raw = path.read_text(encoding="utf-8")
        m = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", raw, re.S)
        if not m:
            continue
        fm = {}
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                fm[k.strip()] = v.strip()
        if fm.get("status") != "approved" or fm.get("message_id"):
            continue
        if datetime.strptime(d.group(1), "%Y-%m-%d").date() > now:
            continue
        media = fm.get("image_file") or fm.get("video_file")
        if media and (REPO / media).exists():
            continue
        if fm.get("video_source"):
            continue
        out.append((path, fm, m.group(2)))
    return out


def make_cover(channel: str, path: Path, fm: dict, body: str) -> str | None:
    """Обложка из пула фонов (уровень 4). Возвращает относительный путь."""
    pick = subprocess.run(
        [sys.executable, str(REPO / "roles/blogger/tools/pick_fallback.py"),
         "--channel", channel],
        cwd=str(REPO), capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    if pick.returncode != 0:
        say(f"FAIL: pick_fallback: {(pick.stderr or pick.stdout or '')[:200]}")
        return None
    bg = pick.stdout.strip().splitlines()[0].strip()
    items = numbered_items(body)
    out = DIGEST / f"cover-{path.stem}.png"
    cmd = [sys.executable, str(REPO / "roles/blogger/tools/digest_cover_photo.py"),
           "--bg", str(REPO / bg), "--out", str(out), "--theme", "auto"]
    if items:
        cmd += ["--items", "|".join(items)]
    cov = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    say((cov.stdout or "").strip()[-400:])
    if cov.returncode != 0 or not out.exists():
        say(f"FAIL: digest_cover_photo: {(cov.stderr or cov.stdout or '')[:300]}")
        return None
    rel = out.relative_to(REPO).as_posix()
    raw = path.read_text(encoding="utf-8")
    m = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", raw, re.S)
    fm_text = re.sub(r"^image_file:.*$\n?", "", m.group(1), flags=re.M)
    new_raw = f"---\n{fm_text}image_file: {rel}\n---\n{m.group(2)}"
    path.write_text(new_raw, encoding="utf-8", newline="\n")
    return rel


def git(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(REPO), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def cover_step(channel: str) -> None:
    targets = find_approved_without_cover(channel)
    if not targets:
        say("обложка: approved-постов без медиа нет — шаг пропущен")
        return
    for path, fm, body in targets:
        say(f"обложка: {path.name} (медиа нет) — собираю из пула фонов")
        rel = make_cover(channel, path, fm, body)
        if not rel:
            continue
        add = git("add", path.relative_to(REPO).as_posix())
        msg = f"roles/blogger: digest build cover for {path.stem}"
        com = git("commit", "-m", msg, "--",
                  path.relative_to(REPO).as_posix())
        if com.returncode != 0:
            say("WARN: коммит обложки не выполнен: " + (com.stderr or "")[-300:])
        else:
            push = git("push", "origin", "main")
            say("push: " + ("ok" if push.returncode == 0
                            else "FAIL " + (push.stderr or "")[-300:]))
        say(f"OK: обложка {rel} -> {path.name}")


def readiness(channel: str) -> None:
    res = subprocess.run(
        [sys.executable, str(REPO / "roles/blogger/tools/publish_scheduled.py"),
         "--channel", channel, "--dry-run"],
        cwd=str(REPO), capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    out = (res.stdout or res.stderr or "").strip()
    say("--- dry-run публикации ---")
    say(out[-1200:] if out else "(вывода нет)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="na100")
    ap.add_argument("--no-cover", action="store_true")
    ap.add_argument("--no-dryrun", action="store_true")
    a = ap.parse_args()

    now = datetime.now(MSK)
    date = now.strftime("%Y-%m-%d")
    say(f"сборка na100: {now:%Y-%m-%d %H:%M:%S} MSK")

    raw = fetch_feeds()
    raw_path = DIGEST / f"raw-{date}.json"
    raw_path.write_text(json.dumps(raw, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    say(f"raw: {raw_path.name}")

    draft = build_draft(raw, date)
    drafts_dir = (REPO / "roles" / "blogger" / "channels" / a.channel / "digests")
    drafts_dir.mkdir(parents=True, exist_ok=True)
    draft_path = drafts_dir / f"{date}-draft.json"
    draft_path.write_text(json.dumps(draft, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    say(f"черновик: {draft_path.relative_to(REPO).as_posix()}")
    # черновик — в git (атрибуция живёт только здесь; решение владельца
    # 12.11.2026): коммит и пуш, чтобы был на всех машинах
    add = git("add", draft_path.relative_to(REPO).as_posix())
    com = git("commit", "-m",
              f"roles/blogger: digest draft {date} ({a.channel})",
              "--", draft_path.relative_to(REPO).as_posix())
    if com.returncode != 0:
        say("WARN: коммит черновика не выполнен: " + (com.stderr or "")[-300:])
    else:
        push = git("push", "origin", "main")
        say("push черновика: " + ("ok" if push.returncode == 0
                                  else "FAIL " + (push.stderr or "")[-300:]))
    say("предложенный отбор:")
    for n in draft["proposed"]:
        say(f"  [{n['region']}] {n['total']:>4} — {n['title'][:80]}")
    for note in draft["notes"]:
        say(f"  * {note}")
    say(f"фиды не ответили: {', '.join(draft['feeds_fail']) or 'нет'}")

    if not a.no_cover:
        say("")
        cover_step(a.channel)
    if not a.no_dryrun:
        say("")
        readiness(a.channel)

    say("")
    say("OK: сборка завершена; текст выпуска пишет агент по черновику")
    flush()


if __name__ == "__main__":
    main()
