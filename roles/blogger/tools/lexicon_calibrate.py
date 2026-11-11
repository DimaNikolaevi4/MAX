# -*- coding: utf-8 -*-
"""Калибровка слоя 3 (humanizer-ru) по факту выпусков.

Зачем: порог номинальности (сущ./глаг. ≤ 2.5) откалиброван под жанр
marketing — для новостного дайджеста он срабатывает почти на каждом выпуске.
Решение 11.11.2026: калибровать по распределению, а не по факту «WARN был».
Данные копит публикатор: каждая публикация дописывает запись {type: scan}
в roles/blogger/channels/<slug>/lexicon-calibration.jsonl (сырой балл,
номинальность, штрафы). Здесь — сводка и ручные метки.

Метки (решение по протоколу калибровки): по 5–10 фрагментам на выпуск
человек помечает «мешает чтению» / «норма жанра» — иначе через N выпусков
не понять, WARN бесполезен или порог не тот.

Команды:
  py roles/blogger/tools/lexicon_calibrate.py summary [--channel na100]
  py roles/blogger/tools/lexicon_calibrate.py label --post <файл.md> \
      --fragment "поставщики памяти двигают цены" --verdict мешает [--note "..."]

verdict: мешает | норма. Запускать с PYTHONIOENCODING=utf-8 (консоль cp1251).
"""
import argparse
import json
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
MSK = timezone(timedelta(hours=3))
THRESHOLD = 2.5  # текущий порог номинальности в humanizer-ru (genre news)


def cal_path(channel: str) -> Path:
    return REPO / "roles" / "blogger" / "channels" / channel / "lexicon-calibration.jsonl"


def load(channel: str) -> tuple[list[dict], list[dict]]:
    scans, labels = [], []
    p = cal_path(channel)
    if not p.exists():
        return scans, labels
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        (scans if rec.get("type") == "scan" else labels).append(rec)
    return scans, labels


def summary(channel: str, limit: int) -> int:
    scans, labels = load(channel)
    if not scans:
        print(f"записей нет: {cal_path(channel)}")
        return 1
    labels_by_post: dict[str, list[dict]] = {}
    for l in labels:
        labels_by_post.setdefault(l.get("post", ""), []).append(l)

    print(f"канал {channel}: сканов {len(scans)}, меток {len(labels)}")
    print()
    print(f"{'дата':<16} {'пост':<42} {'балл':>4} {'сущ/гл':>6} {'номин':>5} {'метки':>5}")
    for s in scans[-limit:]:
        n = labels_by_post.get(s.get("post", ""), [])
        print(f"{(s.get('ts') or '')[:16]:<16} {s.get('post', ''):<42} "
              f"{str(s.get('score') or ''):>4} "
              f"{s.get('noun_verb_ratio', ''):>6} "
              f"{s.get('nominalizations', ''):>5} {len(n):>5}")
        for p in s.get("penalties") or []:
            print(f"{'':<16}   штраф: {p.get('reason')} ({p.get('points')})")
        for l in n:
            fr = (l.get("fragment") or "")[:46]
            print(f"{'':<16}   метка [{l.get('verdict')}]: {fr}")

    ratios = [float(s["noun_verb_ratio"]) for s in scans
              if s.get("noun_verb_ratio") is not None]
    print()
    if ratios:
        q = statistics.quantiles(ratios, n=10) if len(ratios) >= 10 else None
        above = sum(1 for r in ratios if r > THRESHOLD)
        print(f"сущ./глаг.: медиана {statistics.median(ratios):.2f}, "
              f"мин {min(ratios):.2f}, макс {max(ratios):.2f}; "
              f"выше порога {THRESHOLD}: {above}/{len(ratios)}")
        if q:
            print(f"перцентили: p80={q[7]:.2f} p90={q[8]:.2f}")
            if q[7] > THRESHOLD:
                print("вывод: порог ниже реального распределения жанра — "
                      f"кандидат на подъём к p80 ({q[7]:.2f}); "
                      "число оставляем в отчёте как тренд")
        else:
            print(f"(выпусков < 10 — калибровка порога после накопления; "
                  f"сейчас порог {THRESHOLD})")
    bal = [int(s["score"]) for s in scans if s.get("score") is not None]
    if bal:
        print(f"чистота: медиана {statistics.median(bal):.0f}/100, "
              f"мин {min(bal)}, макс {max(bal)}")
    return 0


def label(args) -> int:
    if args.verdict not in ("мешает", "норма"):
        raise SystemExit("verdict: мешает | норма")
    rec = {
        "type": "label",
        "ts": datetime.now(MSK).isoformat(),
        "post": args.post,
        "fragment": args.fragment,
        "verdict": args.verdict,
        "note": args.note or "",
    }
    p = cal_path(args.channel)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("метка записана:", p)
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("summary", help="сводка по выпускам")
    s.add_argument("--channel", default="na100")
    s.add_argument("--limit", type=int, default=30)
    l = sub.add_parser("label", help="ручная метка фрагмента")
    l.add_argument("--channel", default="na100")
    l.add_argument("--post", required=True, help="имя файла поста")
    l.add_argument("--fragment", required=True)
    l.add_argument("--verdict", required=True, choices=["мешает", "норма"])
    l.add_argument("--note", default="")
    a = ap.parse_args()
    sys.exit(summary(a.channel, a.limit) if a.cmd == "summary" else label(a))


if __name__ == "__main__":
    main()
