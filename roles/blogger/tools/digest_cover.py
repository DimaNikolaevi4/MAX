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

Композиция: тёмный фон с холодным свечением, крупный заголовок,
акцентная строка, дата выпуска и подпись снизу.
"""
import argparse
from datetime import datetime, timedelta, timezone
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1400, 788
FONT_B = r"C:\Windows\Fonts\segoeuib.ttf"    # Segoe UI Bold
FONT_SB = r"C:\Windows\Fonts\seguisb.ttf"    # Segoe UI Semibold

MSK = timezone(timedelta(hours=3))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True, help="заголовок, строка 1 (белый)")
    ap.add_argument("--title2", default=None, help="заголовок, строка 2 (акцент)")
    ap.add_argument("--subtitle", default=None, help="подзаголовок под линией")
    ap.add_argument("--footer", default="Новости мира техники")
    ap.add_argument("--show-date", action="store_true",
                    help="добавить MSK-дату первой строкой подписи")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

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

    # --- нижняя подпись: дата (опционально) + футер ---
    footer = a.footer
    if a.show_date:
        footer += f" · {datetime.now(MSK):%d.%m.%Y}"
    text_center(706, footer, foot_f, "#7fa8b8")

    img.save(a.out, "PNG")
    print("ok")


if __name__ == "__main__":
    main()
