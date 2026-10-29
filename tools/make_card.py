# -*- coding: utf-8 -*-
"""Генератор титульной карточки поста (фирменный стиль канала AI).

Использование:
  python tools/make_card.py --title "Строка 1" [--title2 "Строка 2 (акцент)"]
      [--subtitle "подзаголовок"] [--footer "AI · ..."] --out local/card.png

Палитра и композиция повторяют карточку поста 29.10 (тёмный градиент,
неоновые свечения, белый заголовок + акцентная строка, подпись снизу).
"""
import argparse
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1400, 788
FONT_B = r"C:\Windows\Fonts\segoeuib.ttf"    # Segoe UI Bold
FONT_SB = r"C:\Windows\Fonts\seguisb.ttf"    # Segoe UI Semibold


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True, help="заголовок, строка 1 (белый)")
    ap.add_argument("--title2", default=None, help="заголовок, строка 2 (акцент)")
    ap.add_argument("--subtitle", default=None, help="подзаголовок под линией")
    ap.add_argument("--footer", default="AI · тренды искусственного интеллекта")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    img = Image.new("RGB", (W, H), "#0a0e1a")

    # --- фон: диагональный градиент тёмно-синий -> тёмно-фиолетовый ---
    c1, c2 = (10, 14, 26), (30, 18, 58)
    px = img.load()
    for y in range(H):
        for x in range(0, W, 4):
            t = (x / W * 0.45 + y / H * 0.55)
            col = tuple(int(u + (v - u) * t) for u, v in zip(c1, c2))
            for dx in range(4):
                if x + dx < W:
                    px[x + dx, y] = col

    # --- мягкие неоновые свечения ---
    glow = Image.new("RGB", (W, H), "#000000")
    gd = ImageDraw.Draw(glow)
    gd.ellipse([900, -220, 1750, 420], fill="#1b2f55")
    gd.ellipse([-260, 420, 520, 1000], fill="#241542")
    gd.ellipse([560, 540, 1120, 900], fill="#141c3a")
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

    # --- вертикальная компоновка блока заголовка ---
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
        text_center(y2, a.title2, f2, "#7ff3ff")
    d.rounded_rectangle([470, y_line, 930, y_line + 6], radius=3, fill="#7c5cff")

    if a.subtitle:
        text_center(y_line + 52, a.subtitle, sub_f, "#8fa3c8")

    # --- нижняя подпись ---
    text_center(706, a.footer, foot_f, "#8aa0c8")

    img.save(a.out, "PNG")
    print("ok")


if __name__ == "__main__":
    main()
