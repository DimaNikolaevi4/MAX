# -*- coding: utf-8 -*-
"""Заставка «paper» (мачхед слева + панель «ФОРМАТ» справа) поверх фото-фона.

Методика заставок канала na100: docs -> roles/blogger/channels/na100/cover-method.md.
Используется, когда заставку кладут на готовый фон-картинку (пользовательский
фон, сгенерированное изображение). Для заставки «с нуля» есть digest_cover.py.

Использование:
  python roles/blogger/tools/digest_cover_photo.py --bg <фон.png> --out <файл.png> \
      [--theme auto|dark|light] [--items "a|b|c|d|e"] [--accent "Среда, 11 ноября"] \
      [--over "7:30"] [--t1 "Новости ИИ"] [--t2 "и технологий"]

Мачхед (решение владельца 11.11.2026, вечер): надстрока — только время;
название «Новости ИИ / и технологий»; под названием — акцентная строка
цветом «Среда, 11 ноября» (по умолчанию генерируется из текущей даты,
задать свою можно --accent); ниже — подзаголовок «Ежедневный утренний
обзор». Зелёная линия-разделитель убрана — её место заняла акцентная
строка.

theme auto (по умолчанию) — тема определяется по фону: замер зон мачхеда и
              панели, контраст WCAG-подобный, победа по худшей зоне
              (модуль cover_theme.py). Текст всегда противоположен фону.
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
from cover_theme import (accent_date, fit_16_9, fit_text_block, release_stamp,
                         resolve_theme, type_size, OVERLAY_PHOTO_DARK,
                         OVERLAY_PHOTO_LIGHT)

FONT_B = r"C:\Windows\Fonts\segoeuib.ttf"    # Segoe UI Bold
FONT_SB = r"C:\Windows\Fonts\seguisb.ttf"    # Segoe UI Semibold
MSK = timezone(timedelta(hours=3))

# базовая геометрия рассчитана на 2752x1536; масштабируется по высоте
BASE_H = 1536


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bg", required=True, help="фоновая картинка (PNG/JPG)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--theme", choices=["auto", "dark", "light"], default="auto",
                    help="auto — тема по фону (контраст, худшая зона)")
    ap.add_argument("--over", default=None,
                    help="надстрока; по умолчанию — только время выпуска")
    ap.add_argument("--t1", default="Новости ИИ")
    ap.add_argument("--t2", default="и технологий")
    ap.add_argument("--accent", default="",
                    help="акцентная строка цветом; пусто — «Среда, 11 ноября» "
                         "(автодата выпуска)")
    ap.add_argument("--sub", default="Ежедневный утренний обзор")
    ap.add_argument("--items", default="",
                    help="пункты панели через | (обычно 5 заголовков выпуска)")
    ap.add_argument("--no-date", action="store_true")
    ap.add_argument("--wash", type=float, default=0.0,
                    help="полупрозрачная подложка на ВСЁ изображение, 0..1 "
                         "(0 = выкл); цвет темы — как у панели справа; "
                         "вводил решение владельца 11.11.2026 для светлых "
                         "фонов, где заголовок плохо читается")
    a = ap.parse_args()

    im = Image.open(a.bg).convert("RGBA")
    im, ar_note = fit_16_9(im)
    if im is None:
        raise SystemExit(f"background not 16:9: {ar_note} (crop it or use another source)")
    print(ar_note)
    theme, auto_note = resolve_theme(a.theme, im, OVERLAY_PHOTO_DARK, OVERLAY_PHOTO_LIGHT)
    if auto_note:
        print(auto_note)
    dark = theme == "dark"

    if a.wash > 0:
        # подложка на весь кадр цветом темы (решение владельца 11.11.2026):
        # светлый фон -> белая вуаль, тёмный -> тёмная, контраст растёт
        wash_a = min(1.0, a.wash)
        fill = (255, 255, 255, round(wash_a * 255)) if not dark \
            else (5, 10, 18, round(wash_a * 255))
        im.alpha_composite(Image.new("RGBA", im.size, fill))
        print(f"wash: {wash_a:.2f} ({'белая' if not dark else 'тёмная'})")

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

    # безопасная ширина мачхеда: от LX до внутренней кромки панели с отступом
    # (текст не должен заходить на панель «ФОРМАТ» — правило подгонки 11.11)
    px1 = round(1640 * s)
    mast_w = px1 - round(60 * s) - LX

    def fit1(text, font_path, start, min_size):
        size, lines, trunc = fit_text_block(text, font_path, mast_w,
                                            max_lines=1, start=start,
                                            min_size=min_size)
        return size, lines[0], trunc

    ov_size, over_txt, ov_tr = fit1(a.over or release_stamp(datetime.now(MSK)),
                                    FONT_SB, type_size(H, "over"),
                                    round(type_size(H, "over") * 0.72))
    t1_size, t1_txt, t1_tr = fit1(a.t1, FONT_B, type_size(H, "title"),
                                  type_size(H, "title_min"))
    t2_size, t2_txt, t2_tr = fit1(a.t2, FONT_B, type_size(H, "title"),
                                  type_size(H, "title_min"))
    acc_txt = a.accent.strip() or accent_date(datetime.now(MSK))
    acc_size, acc_txt, acc_tr = fit1(acc_txt, FONT_SB, type_size(H, "accent"),
                                     type_size(H, "accent_min"))
    sub_size, sub_txt, sub_tr = fit1(a.sub, FONT_SB, type_size(H, "sub"),
                                     type_size(H, "sub_min"))
    for name, trunc in (("over", ov_tr), ("t1", t1_tr), ("t2", t2_tr),
                        ("accent", acc_tr), ("sub", sub_tr)):
        if trunc:
            print(f"warning: masthead '{name}' truncated to fit")

    d.text((LX, round(210 * s)), over_txt, font=ImageFont.truetype(FONT_SB, ov_size), fill=col_blue)

    # название «Новости ИИ / и технологий» — по вертикальному центру мачхеда
    # (решение 11.11.2026: блок название+акцент+подзаголовок центрируется между
    # надстрокой и футером; раньше t1/t2 стояли на жёстких 330s/590s, название
    # висело высоко, а низ мачхеда пустовал)
    t1_h = round(t1_size * 1.16)
    t2_h = round(t2_size * 1.16)
    acc_h = round(acc_size * 1.24)
    sub_h = round(sub_size * 1.22)
    gap_t2 = round(60 * s)      # между строками названия
    gap_acc = round(56 * s)     # название -> акцентная строка с датой
    gap_sub = round(46 * s)     # акцент -> подзаголовок
    zone_top = round(210 * s) + round(ov_size * 1.5)
    zone_bot = round(1380 * s) - round(40 * s)
    group_h = t1_h + gap_t2 + t2_h + gap_acc + acc_h + gap_sub + sub_h
    y_t1 = zone_top + max(0, (zone_bot - zone_top - group_h) // 2)
    y_t2 = y_t1 + t1_h + gap_t2
    y_acc = y_t2 + t2_h + gap_acc
    y_sub = y_acc + acc_h + gap_sub

    d.text((LX, y_t1), t1_txt, font=ImageFont.truetype(FONT_B, t1_size), fill=col_text)
    d.text((LX, y_t2), t2_txt, font=ImageFont.truetype(FONT_B, t2_size), fill=col_text)
    # акцентная строка цветом вместо зелёной линии (решение владельца
    # 11.11.2026, вечер: «Среда, 11 ноября» под названием)
    d.text((LX, y_acc), acc_txt, font=ImageFont.truetype(FONT_SB, acc_size), fill=col_green)
    # подзаголовок приглушённый: акцентная строка должна выделяться цветом
    # (в светлой теме mint совпадал с зелёным акцентом — строки сливались)
    d.text((LX, y_sub), sub_txt, font=ImageFont.truetype(FONT_SB, sub_size), fill=col_gray)

    foot_f = ImageFont.truetype(FONT_SB, type_size(H, "footer"))
    d.text((LX, round(1380 * s)), "max.ru/channel_na100", font=foot_f, fill=col_gray)
    # нижняя дата убрана (решение 11.11.2026, вечер): дата есть только
    # в надстройке выпуска сверху; --no-date оставлен для совместимости

    # правая колонка «ФОРМАТ»
    if a.items:
        RX = round(1790 * s)
        d.text((RX, round(236 * s)), "Ф О Р М А Т",
               font=ImageFont.truetype(FONT_SB, type_size(H, "fmt")), fill=col_blue)
        items = [x.strip() for x in a.items.split("|") if x.strip()]

        row_y = round(388 * s)
        step = round(212 * s)
        num_f = ImageFont.truetype(FONT_B, type_size(H, "num"))
        text_x = RX + round(170 * s)
        # безопасная ширина пункта: до внутренней кромки панели с отступом 48s
        max_w = px2 - round(48 * s) - text_x
        for i, s_item in enumerate(items, start=1):
            d.text((RX, row_y), f"0{i}", font=num_f, fill=col_green)
            # подгонка: перенос (до 2 строк) -> уменьшение кегля -> «…»
            size, lines, trunc = fit_text_block(s_item, FONT_B, max_w,
                                                max_lines=2,
                                                start=type_size(H, "item"),
                                                min_size=type_size(H, "item_min"))
            f_t = ImageFont.truetype(FONT_B, size)
            lh = round(size * 1.18)
            for k, ln in enumerate(lines):
                d.text((text_x, row_y + round(8 * s) + k * lh), ln,
                       font=f_t, fill=col_text)
            if trunc:
                print(f"warning: panel item {i} truncated to fit")
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
