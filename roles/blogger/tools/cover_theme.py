# -*- coding: utf-8 -*-
"""Автовыбор темы заставки «paper» по фону: тёмный фон -> светлый текст,
светлый фон -> тёмный текст (наилучшая читаемость).

Логика (решение 11.11.2026, задача «определяем основной фон и делаем надписи
противоположного цвета»):
  1. Фон сэмплируется по двум зонам раскладки: мачхед (левые ~55% ширины,
     где лежит заголовок) и панель «ФОРМАТ» (правые ~40%, где лежат пункты).
  2. Для каждой темы считается ЭФФЕКТИВНЫЙ фон зоны: пиксели фона, смешанные
     с подложкой темы (тёмный градиент/чёрная панель или белая панель).
  3. Считается контраст WCAG-подобного отношения (линеаризованная
     относительная luminance) между цветом текста темы и эффективным фоном.
  4. Побеждает тема с большим контрастом в ХУДШЕЙ зоне — текст должен читаться
     и в мачхеде, и в панели одновременно.

Используется digest_cover_photo.py и digest_cover_video.py (--theme auto,
значение по умолчанию); ручной --theme dark|light сохранён как override.
"""
from PIL import Image, ImageFont

# зоны раскладки в долях размера кадра: (x0, x1, y0, y1)
ZONES = {
    "masthead": (0.02, 0.55, 0.12, 0.80),
    "panel": (0.58, 0.96, 0.10, 0.90),
}

NAVY = (0x16, 0x30, 0x5E)   # текст light-темы (#16305E)
WHITE = (0xFF, 0xFF, 0xFF)  # текст dark-темы


def _lin(c: float) -> float:
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def rel_lum(rgb) -> float:
    """Относительная luminance (WCAG): 0..1, с линеаризацией sRGB."""
    r, g, b = rgb[:3]
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def zone_lums(im: Image.Image, zones=ZONES) -> dict:
    """Средняя относительная luminance по зонам (доли размера кадра)."""
    rgb = im.convert("RGB")
    small = rgb.resize((128, max(1, round(128 * rgb.height / rgb.width))))
    px = small.load()
    W, H = small.size
    out = {}
    for name, (x0, x1, y0, y1) in zones.items():
        acc = n = 0
        for yy in range(max(0, round(y0 * H)), min(H, round(y1 * H))):
            for xx in range(max(0, round(x0 * W)), min(W, round(x1 * W))):
                acc += rel_lum(px[xx, yy])
                n += 1
        out[name] = acc / n if n else 0.0
    return out


def contrast(la: float, lb: float) -> float:
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _eff(bg: float, ov) -> float:
    """Эффективный фон зоны: bg, смешанный с подложкой (alpha, rgb) или None."""
    if ov is None:
        return bg
    alpha, col = ov
    return bg * (1 - alpha) + rel_lum(col) * alpha


def choose_theme(zl: dict, dark_overlay: dict, light_overlay: dict):
    """Выбор темы по худшей зоне.

    zl — результат zone_lums(); dark_overlay / light_overlay —
    {"masthead": (alpha, rgb) | None, "panel": (alpha, rgb) | None}.
    Возвращает (theme, {"masthead": cr, "panel": cr, "score": min}).
    """
    text_lum = {"dark": rel_lum(WHITE), "light": rel_lum(NAVY)}
    result = {}
    for theme in ("dark", "light"):
        ovs = dark_overlay if theme == "dark" else light_overlay
        cr = {z: contrast(text_lum[theme], _eff(bg, ovs.get(z)))
              for z, bg in zl.items()}
        cr["score"] = min(cr[z] for z in zl)
        result[theme] = cr
    theme = "dark" if result["dark"]["score"] >= result["light"]["score"] else "light"
    return theme, result


# описания подложек по инструментам (alpha 0..1, цвет RGB)
OVERLAY_PHOTO_DARK = {"masthead": (0.33, (5, 10, 18)),    # градиент затемнения слева (в среднем)
                      "panel": (0.47, (7, 16, 24))}       # панель чёрная ~47%
OVERLAY_PHOTO_LIGHT = {"masthead": None,
                       "panel": (0.72, (255, 255, 255))}  # панель белая ~72%
OVERLAY_VIDEO_DARK = {"masthead": None,                  # у видео-инструмента нет левого градиента
                      "panel": (0.45, (0, 0, 0))}        # drawbox black@0.45
OVERLAY_VIDEO_LIGHT = {"masthead": None,
                       "panel": (0.72, (255, 255, 255))}  # drawbox white@0.72


def resolve_theme(arg: str, im: Image.Image, overlay_dark: dict, overlay_light: dict):
    """--theme auto|dark|light -> ('dark'|'light', диагностическая строка)."""
    if arg != "auto":
        return arg, ""
    zl = zone_lums(im)
    theme, cr = choose_theme(zl, overlay_dark, overlay_light)
    line = (f"auto: masthead L={zl['masthead']:.3f}, panel L={zl['panel']:.3f} "
            f"-> {theme} (contrast dark={cr['dark']['score']:.2f}, "
            f"light={cr['light']['score']:.2f})")
    return theme, line


TARGET_AR = 16 / 9
ASPECT_TOL = 0.15   # допуск отклонения от 16:9 (±15%)

WEEKDAYS_RU = ["Понедельник", "Вторник", "Среда", "Четверг",
               "Пятница", "Суббота", "Воскресенье"]


def release_stamp(dt) -> str:
    """Надстрока выпуска вместо «Т Е Х Н О - Д А Й Д Ж Е С Т» (решение
    11.11.2026): реальное время, дата, день недели — «7:30 11.11.2026 Среда»."""
    return f"{dt.hour}:{dt:%M} {dt:%d.%m.%Y} {WEEKDAYS_RU[dt.weekday()]}"


def aspect_info(im: Image.Image):
    """(соотношение сторон, отклонение от 16:9 в долях: 1.0 = идеально)."""
    ar = im.width / im.height
    return ar, ar / TARGET_AR


def fit_16_9(im: Image.Image, tol: float = ASPECT_TOL):
    """Проверка фона на 16:9 (проверено на практике 11.11.2026: обложки
    канала — 2752x1536 и 1920x1080, оба ~16:9).

    В пределах допуска ±15% — центр-кроп до точных 16:9 (возвращает кадр).
    Вне допуска (4:3, 3:2, портретные) — (None, причина): кадр бракуется,
    пайплайн переходит к следующему источнику/заставке.
    """
    ar, rel = aspect_info(im)
    if abs(rel - 1) > tol:
        return None, f"aspect {ar:.3f} ({rel:.2f}x of 16:9) outside tolerance +-{tol:.0%}, rejected"
    W, H = im.size
    if rel > 1:    # шире 16:9 — режем бока
        nw = round(H * TARGET_AR)
        x0 = (W - nw) // 2
        im = im.crop((x0, 0, x0 + nw, H))
    elif rel < 1:  # выше 16:9 — режем верх/низ по центру
        nh = round(W / TARGET_AR)
        y0 = (H - nh) // 2
        im = im.crop((0, y0, W, y0 + nh))
    return im, f"aspect {ar:.3f} ({rel:.2f}x of 16:9) -> center-crop to 16:9"


# --- Подгонка текста: перенос -> уменьшение кегля -> многоточие ---
# Введено 11.11.2026 по итогам поста AaHI4ZuyEec (пункт 03 «ФОРМАТ» вылезал
# за затенение панели). Правило: текст живёт внутри безопасной зоны
# (внутренняя ширина панели/мачхеда с отступом), приоритет подгонки —
# перенос строк (сохраняет кегль), затем уменьшение шрифта до min_size,
# затем обрезка с «…» (крайняя мера). Профилактика — короткие формулировки
# тем на этапе сборки выпуска (3–5 слов, cover-method.md).

def wrap_lines(text: str, font, max_w: float) -> list:
    """Перенос по словам под ширину max_w (px). Одиночное слово шире max_w
    режется по символам."""
    words = text.split()
    if not words:
        return [""]
    lines, cur = [], words[0]
    for w in words[1:]:
        trial = f"{cur} {w}"
        if font.getlength(trial) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    out = []
    for ln in lines:
        if font.getlength(ln) <= max_w or not ln:
            out.append(ln)
            continue
        chunk = ""
        for ch in ln:
            if chunk and font.getlength(chunk + ch) > max_w:
                out.append(chunk)
                chunk = ch
            else:
                chunk += ch
        out.append(chunk)
    return out


def fit_text_block(text: str, font_path: str, max_w: float, max_lines: int = 2,
                   start: int = 56, min_size: int = 30, step: int = 2):
    """Возвращает (size, lines, truncated): минимально инвазивная подгонка.

    Уровень 1 — перенос строк при исходном кегле (len(lines) <= max_lines).
    Уровень 2 — кегль уменьшается на step, пока блок не войдёт по строкам.
    Уровень 3 — на min_size берутся первые max_lines строк, последняя
    обрезается с «…».
    """
    size = start
    while size >= min_size:
        font = ImageFont.truetype(font_path, size)
        lines = wrap_lines(text, font, max_w)
        if len(lines) <= max_lines:
            return size, lines, False
        size -= step
    font = ImageFont.truetype(font_path, min_size)
    lines = wrap_lines(text, font, max_w)[:max_lines]
    last = lines[-1] if lines else ""
    tail = ""
    while last and font.getlength(last + "…") > max_w:
        last = last[:-1]
    lines[-1] = last.rstrip() + "…" if last else "…"
    return min_size, lines, True
