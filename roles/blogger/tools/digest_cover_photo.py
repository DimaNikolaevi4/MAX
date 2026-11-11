# -*- coding: utf-8 -*-
"""Заставка «paper» (мачхед слева + панель «ФОРМАТ» справа) поверх фото-фона.

Методика заставок канала na100: docs -> roles/blogger/channels/na100/cover-method.md.
Используется, когда заставку кладут на готовый фон-картинку (пользовательский
фон, сгенерированное изображение). Для заставки «с нуля» есть digest_cover.py.

Использование:
  python roles/blogger/tools/digest_cover_photo.py --bg <фон.png> --out <файл.png> \
      [--theme dark|light] [--items "a|b|c|d|e"] [--sub "итоги суток"] [--no-date]

theme dark  — светлый текст для тёмного фона (градиент затемнения слева,
              полупрозрачная тёмная панель);
theme light — тёмно-синий текст для светлого фона (полупрозрачная белая панель).

Проверено 11.11.2026: пост https://max.ru/channel_na100/AaHI4SMuBW0
(тёмный фон 2752x1536, theme dark).
"""
import argparse
from datetime import datetime, timedelta, timezone
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

FONT_B = r"C:\Windows\Fonts\segoeuib.ttf"    # Segoe UI Bold
FONT_SB = r"C:\Windows\Fonts\seguisb.ttf"    # Segoe UI Semibold
MSK = timezone(timedelta(hours=3))

# базовая геометрия рассчитана на 2752x1536; масштабируется по высоте
BASE_H = 1536


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bg", required=True, help="фоновая картинка (PNG/JPG)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--theme", choices=["dark", "light"], default="dark")
    ap.add_argument("--over", default="Т Е Х Н О - Д А Й Д Ж Е С Т")
    ap.add_argument("--t1", default="Новости")
    ap.add_argument("--t2", default="мира техники")
    ap.add_argument("--sub", default="итоги суток")
    ap.add_argument("--items", default="",
                    help="пункты панели через | (обычно 5 заголовков выпуска)")
    ap.add_argument("--no-date", action="store_true")
    a = ap.parse_args()

    dark = a.theme == "dark"
    im = Image.open(a.bg).convert("RGBA")
    W, H = im.size
    s = H / BASE_H
    LX = round(190 * s)
    RM = W - LX
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)

    if dark:
        # затемнение слева градиентом — читаемость мачхеда на тёмном фото
        grad = Image.new("L", (W, 1), 0)
        g_end = round(1560 * s)
        for x in range(W):
            if x < g_end:
                grad.putpixel((x, 0), int(170 * (1 - x / g_end)))
        grad = grad.resize((W, H))
        dim = Image.new("RGBA", (W, H), (5, 10, 18, 255))
        dim.putalpha(grad)
        im.alpha_composite(dim)

    if a.items:
        # панель «ФОРМАТ»: подложка + вертикальный разделитель
        px1 = round(1640 * s)
        px2 = round(2680 * s)
        if dark:
            d.rounded_rectangle([px1, round(140 * s), px2, round(1408 * s)],
                                radius=round(28 * s), fill=(7, 16, 24, 120))
        else:
            d.rounded_rectangle([px1, round(140 * s), px2, round(1408 * s)],
                                radius=round(28 * s), fill=(255, 255, 255, 184))
        d.line([round(1712 * s), round(210 * s), round(1712 * s), round(1338 * s)],
               fill=(143, 184, 200, 120) if dark else (22, 48, 94, 77), width=max(2, round(3 * s)))

    col_text = (255, 255, 255, 255) if dark else (22, 48, 94, 255)      # текст
    col_green = (62, 219, 154, 255) if dark else (31, 157, 102, 255)    # акцент
    col_mint = (127, 255, 212, 255) if dark else (31, 157, 102, 255)   # подзаголовок
    col_blue = (159, 196, 212, 255) if dark else (74, 110, 140, 255)   # надстрока
    col_gray = (143, 184, 200, 255) if dark else (74, 110, 140, 255)   # футер/дата

    d.text((LX, round(210 * s)), a.over, font=ImageFont.truetype(FONT_SB, round(56 * s)), fill=col_blue)
    d.text((LX, round(330 * s)), a.t1, font=ImageFont.truetype(FONT_B, round(200 * s)), fill=col_text)
    d.text((LX, round(590 * s)), a.t2, font=ImageFont.truetype(FONT_B, round(200 * s)), fill=col_text)
    d.rounded_rectangle([LX, round(868 * s), LX + round(460 * s), round(880 * s)],
                        radius=round(6 * s), fill=col_green)
    d.text((LX, round(950 * s)), a.sub, font=ImageFont.truetype(FONT_SB, round(84 * s)), fill=col_mint)

    foot_f = ImageFont.truetype(FONT_SB, round(56 * s))
    d.text((LX, round(1380 * s)), "max.ru/channel_na100", font=foot_f, fill=col_gray)
    if not a.no_date:
        date_s = f"{datetime.now(MSK):%d.%m.%Y}"
        d.text((RM - d.textlength(date_s, font=foot_f), round(1290 * s)), date_s,
               font=foot_f, fill=col_gray)

    # правая колонка «ФОРМАТ»
    if a.items:
        RX = round(1790 * s)
        d.text((RX, round(236 * s)), "Ф О Р М А Т",
               font=ImageFont.truetype(FONT_SB, round(52 * s)), fill=col_blue)
        items = [x.strip() for x in a.items.split("|") if x.strip()]

        def fit(s_txt, max_w, start):
            f = ImageFont.truetype(FONT_B, start)
            while d.textlength(s_txt, font=f) > max_w and start > 30:
                start -= 2
                f = ImageFont.truetype(FONT_B, start)
            return f

        row_y = round(388 * s)
        step = round(212 * s)
        num_f = ImageFont.truetype(FONT_B, round(64 * s))
        for i, s_item in enumerate(items, start=1):
            d.text((RX, row_y), f"0{i}", font=num_f, fill=col_green)
            f_t = fit(s_item, RM - RX - round(170 * s), round(56 * s))
            d.text((RX + round(170 * s), row_y + round(8 * s)), s_item, font=f_t, fill=col_text)
            if i < len(items):
                d.line([RX, row_y + round(152 * s), RM, row_y + round(152 * s)],
                       fill=(143, 184, 200, 110) if dark else (22, 48, 94, 64),
                       width=max(2, round(3 * s)))
            row_y += step

    out = Image.alpha_composite(im, overlay).convert("RGB")
    out.save(a.out, "PNG", optimize=True)
    print("ok (photo-paper)", out.size)


if __name__ == "__main__":
    main()
