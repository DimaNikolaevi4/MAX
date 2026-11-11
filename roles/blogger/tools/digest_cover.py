# -*- coding: utf-8 -*-
"""Генератор брендированной заставки техно-дайджеста канала na100.

Штатная часть пайплайна дайджеста (протокол docs/na100-relaunch-2026-11-10.md,
решение от 10.11.2026, пункт 5 разбора консультантов): используется, когда
нет фото из whitelist. Для других генераторов действует запрет из AGENTS.md —
этот скрипт охватывает только заставку дайджеста na100.

Использование:
  python roles/blogger/tools/digest_cover.py --title "пятёрка" \
      [--title2 "новостей"] [--subtitle "что случилось за сутки"] \
      [--footer "Техно-дайджест"] --out local/digest/cover-YYYY-MM-DD.png

Стиль paper (заставка-оглавление): слова названия могут идти в двух строках
(--title / --title2), справа колонка «формат» из --items "a|b|c".

Композиция: тёмный фон с холодным свечением, крупный заголовок,
акцентная строка, дата выпуска и подпись снизу.
"""
import argparse
from datetime import datetime, timedelta, timezone
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from cover_theme import release_stamp

W, H = 1400, 788
FONT_B = r"C:\Windows\Fonts\segoeuib.ttf"    # Segoe UI Bold
FONT_SB = r"C:\Windows\Fonts\seguisb.ttf"    # Segoe UI Semibold

MSK = timezone(timedelta(hours=3))


def _make_paper(a) -> None:
    """Стиль paper: заставка-оглавление.

    Слева мачхед: надстрока, крупное название, акцентная линия, подзаголовок,
    футер с ссылкой канала и датой. Справа — колонка «формат» с пунктами из
    --items. Репродюсируется программно, без внешних изображений.
    """
    img = Image.new("RGB", (W, H), "#07141b")

    c1, c2 = (7, 20, 27), (18, 30, 55)
    px = img.load()
    for y in range(H):
        t_y = y / H * 0.55
        for x in range(0, W, 4):
            t = x / W * 0.45 + t_y
            col = tuple(int(u + (v - u) * t) for u, v in zip(c1, c2))
            for dx in range(4):
                if x + dx < W:
                    px[x + dx, y] = col

    glow = Image.new("RGB", (W, H), "#000000")
    gd = ImageDraw.Draw(glow)
    gd.ellipse([-360, -300, 380, 260], fill="#123a4a")     # левый верх
    gd.ellipse([880, 420, 1560, 1000], fill="#0e3326")     # правый низ
    gd.ellipse([540, 560, 1120, 900], fill="#101f38")
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    img = Image.blend(img, Image.blend(img, glow, 0.55), 0.9)
    d = ImageDraw.Draw(img)

    def fit_left(s, max_w, start):
        f = ImageFont.truetype(FONT_B, start)
        while d.textlength(s, font=f) > max_w and start > 22:
            start -= 2
            f = ImageFont.truetype(FONT_B, start)
        return f

    LX = 96
    over_txt = a.over or release_stamp(datetime.now(MSK))
    d.text((LX, 112), over_txt,
           font=ImageFont.truetype(FONT_SB, 34), fill="#8fb8c8")

    # название — по вертикальному центру мачхеда (решение 11.11.2026): блок
    # название+линия+подзаголовок центрируется между надстройкой и футером —
    # раньше название стояло на жёстком y=168 и висело высоко
    t1_f = fit_left(a.title, 660, 96)
    t1_h = t1_f.size + 22
    t2_f = fit_left(a.title2, 660, 96) if a.title2 else None
    t2_h = (t2_f.size + 22) if t2_f else 0
    line_h, gap_line, gap_sub = 6, 40, 46
    sub_h = 48 if a.subtitle else 0
    zone_top = 112 + 42          # низ надстроки (28 * 1.5)
    zone_bot = 716 - 20          # верх футера
    group_h = t1_h + t2_h + gap_line + line_h + (gap_sub + sub_h if sub_h else 0)
    y_t1 = zone_top + max(0, (zone_bot - zone_top - group_h) // 2)

    d.text((LX, y_t1), a.title, font=t1_f, fill="#ffffff")
    y2 = y_t1 + t1_h
    if t2_f:
        d.text((LX, y2), a.title2, font=t2_f, fill="#ffffff")
        y_line = y2 + t2_h + 18
    else:
        y_line = y2 + 28
    d.rounded_rectangle([LX, y_line, LX + 232, y_line + line_h], radius=3, fill="#3edb9a")

    if a.subtitle:
        d.text((LX, y_line + line_h + gap_sub), a.subtitle,
               font=ImageFont.truetype(FONT_SB, 40), fill="#7fffd4")

    foot_f = ImageFont.truetype(FONT_SB, 27)
    d.text((LX, 716), "max.ru/channel_na100", font=foot_f, fill="#7fa8b8")
    # нижняя дата в paper-стиле убрана (решение 11.11.2026, вечер):
    # дата есть только в надстройке выпуска сверху
    # (--show-date/--no-date действуют для стиля dark)

    # --- правая колонка «формат» ---
    if a.items:
        RX, RM = 904, W - 96
        d.line([860, 108, 860, 690], fill="#23405a", width=2)
        d.text((RX, 116), "Ф О Р М А Т",
               font=ImageFont.truetype(FONT_SB, 26), fill="#8fb8c8")

        items = [s.strip() for s in a.items.split("|") if s.strip()]
        row_y = 186
        for i, s in enumerate(items, start=1):
            d.text((RX, row_y), f"0{i}",
                   font=ImageFont.truetype(FONT_B, 34), fill="#3edb9a")
            f_t = fit_left(s, RM - RX - 92, 30)
            d.text((RX + 92, row_y + 4), s, font=f_t, fill="#edf4f8")
            if i < len(items):
                d.line([RX, row_y + 78, RM, row_y + 78], fill="#23405a", width=2)
            row_y += 110

    img.save(a.out, "PNG")
    print("ok (paper)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True, help="заголовок, строка 1 (белый)")
    ap.add_argument("--title2", default=None, help="заголовок, строка 2 (акцент)")
    ap.add_argument("--subtitle", default=None, help="подзаголовок под линией")
    ap.add_argument("--footer", default=None,
                    help="подпись перед датой; по умолчанию None (только дата)")
    ap.add_argument("--show-date", action="store_true", default=True,
                    help="добавить MSK-дату первой строкой подписи")
    ap.add_argument("--no-date", dest="show_date", action="store_false")
    ap.add_argument("--over", default=None,
                    help="надстрока paper-стиля; по умолчанию — время, дата, "
                         "день недели выпуска (вместо «Т Е Х Н О - Д А Й Д Ж Е С Т»)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--style", choices=["dark", "paper"], default="dark",
                    help="dark — центрированная классика; paper — заставка-"
                         "оглавление (мачхед слева, формат канала справа)")
    ap.add_argument("--items", default="",
                    help="пункты оглавления через | (только style=paper)")
    a = ap.parse_args()

    if a.style == "paper":
        _make_paper(a)
        return

    img = Image.new("RGB", (W, H), "#07141b")

    # --- фон: диагональный градиент тёмный сине-зелёный -> тёмный синий ---
    c1, c2 = (7, 20, 27), (18, 30, 55)
    px = img.load()
    for y in range(H):
        for x in range(0, W, 4):
            t = (x / W * 0.45 + y / H * 0.55)
            col = tuple(int(u + (v - u) * t) for u, v in zip(c1, c2))
            for dx in range(4):
                if x + dx < W:
                    px[x + dx, y] = col

    # --- мягкие свечения (холодная зелёно-голубая гамма, отличим от AI-канала) ---
    glow = Image.new("RGB", (W, H), "#000000")
    gd = ImageDraw.Draw(glow)
    gd.ellipse([880, -240, 1780, 400], fill="#123a4a")
    gd.ellipse([-280, 430, 560, 1020], fill="#0e3326")
    gd.ellipse([520, 560, 1140, 920], fill="#101f38")
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    img = Image.blend(img, Image.blend(img, glow, 0.55), 0.9)
    d = ImageDraw.Draw(img)

    def text_center(y, s, font, fill):
        w = d.textlength(s, font=font)
        d.text(((W - w) / 2, y), s, font=font, fill=fill)

    def fit(s, size, max_w=1200):
        f = ImageFont.truetype(FONT_B, size)
        while d.textlength(s, font=f) > max_w and size > 40:
            size -= 4
            f = ImageFont.truetype(FONT_B, size)
        return f

    size = 74
    f1 = fit(a.title, size)
    f2 = fit(a.title2, size) if a.title2 else None
    sub_f = ImageFont.truetype(FONT_SB, 38)
    foot_f = ImageFont.truetype(FONT_SB, 32)

    lh = 98
    if a.title2:
        y1 = 120
        y2 = y1 + lh
        y_line = y2 + 108
    else:
        y1 = 168
        y_line = y1 + lh + 10
    text_center(y1, a.title, f1, "#ffffff")
    if a.title2:
        text_center(y2, a.title2, f2, "#7fffd4")
    d.rounded_rectangle([470, y_line, 930, y_line + 6], radius=3, fill="#3edb9a")

    if a.subtitle:
        text_center(y_line + 52, a.subtitle, sub_f, "#8fb8c8")

    # --- нижняя подпись: дата (по умолчанию) + опциональный футер ---
    parts = []
    if a.footer:
        parts.append(a.footer)
    if a.show_date:
        parts.append(f"{datetime.now(MSK):%d.%m.%Y}")
    footer = " · ".join(parts)
    if footer:
        text_center(706, footer, foot_f, "#7fa8b8")

    img.save(a.out, "PNG")
    print("ok")


if __name__ == "__main__":
    main()
