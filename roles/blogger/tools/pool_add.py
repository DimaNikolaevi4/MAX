# -*- coding: utf-8 -*-
"""Добавление фонов в пул fallback-заставок канала na100.

Пул — шаг 4 цепочки поставки изображения (решение 11.11.2026): если
Commons / фотобанки / RSS allowed ничего не дали, берётся случайный фон
из пула и поверх него накладывается брендированная плашка
(digest_cover_photo.py). Фоны — материал владельца, поэтому внешняя
атрибуция не нужна (заставка, а не «Фото:/Иллюстрация:»).

Инструмент:
  py roles/blogger/tools/pool_add.py <папка-источник> [--delete]

Что делает с каждым изображением:
  1. центр-кроп до точных 16:9 (пул единообразен; исходное соотношение
     пишется в метаданные);
  2. уменьшение до ширины <= 2560 (репозиторий лёгкий, MAX всё равно
     сжимает до 1920);
  3. конвертация в JPEG q85 (RGB) — пул фонов всегда JPEG (проверено
     11.11.2026: пересжатые PIL-ом PNG раздуваются в 4-6 раз);
  4. разбор по зонам раскладки (cover_theme.zone_lums + choose_theme):
     цвет фона, тема (dark/light), цвет контрастного текста, цвет и
     прозрачность бокового затенения (панели и мачхеда) — в
     fallback_images.json рядом с картинками.

Использование в пайплайне: случайный фон —
  py roles/blogger/tools/pick_fallback.py --channel na100
"""
import argparse
import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from cover_theme import (choose_theme, zone_lums, OVERLAY_PHOTO_DARK,
                         OVERLAY_PHOTO_LIGHT)

POOL = Path("roles/blogger/channels/na100/images/fallback")
META = POOL / "fallback_images.json"

MAX_W = 2560          # ширина пула (MAX сжимает до 1920)
JPEG_Q = 85

TEXT_COLOR = {"dark": "#FFFFFF", "light": "#16305E"}
ACCENT = {"dark": "#3EDB9A", "light": "#1F9D66"}
# боковое затенение (панель/мачхед) из digest_cover_photo.py:
SHADING = {
    "dark": {"panel": {"color": "#071018", "alpha": 0.47},
             "masthead": {"color": "#050A12", "alpha": 0.33}},
    "light": {"panel": {"color": "#FFFFFF", "alpha": 0.72},
              "masthead": None},
}


def hexc(rgb) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb[:3])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="папка с исходными изображениями")
    ap.add_argument("--delete", action="store_true",
                    help="удалить источник после успешной обработки (перемещение)")
    a = ap.parse_args()

    src = Path(a.source)
    if not src.is_dir():
        raise SystemExit(f"no such folder: {src}")
    POOL.mkdir(parents=True, exist_ok=True)
    meta = json.loads(META.read_text(encoding="utf-8")) if META.exists() else {}

    files = [p for p in sorted(src.iterdir()) if p.is_file() and
             p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
    if not files:
        raise SystemExit("no images found in source folder")

    for p in files:
        im = Image.open(p)
        im.load()
        src_ar = round(im.width / im.height, 3)
        # центр-кроп до точных 16:9
        tgt = 16 / 9
        if im.width / im.height > tgt:
            nw = round(im.height * tgt)
            x0 = (im.width - nw) // 2
            im = im.crop((x0, 0, x0 + nw, im.height))
        elif im.width / im.height < tgt:
            nh = round(im.width / tgt)
            y0 = (im.height - nh) // 2
            im = im.crop((0, y0, im.width, y0 + nh))
        if im.width > MAX_W:
            im = im.resize((MAX_W, round(im.height * MAX_W / im.width)),
                           Image.LANCZOS)

        out_name = p.name if p.suffix.lower() not in (".jpeg",) else p.stem + ".jpg"
        out_path = POOL / out_name
        # JPEG всегда (пул фонов — фото/рендеры; проверено 11.11.2026:
        # пересжатые PIL-ом PNG раздуваются в 4-6 раз, JPEG q85 легче и
        # без видимых потерь на фоне)
        out_path = out_path.with_suffix(".jpg")
        im.convert("RGB").save(out_path, "JPEG", quality=JPEG_Q)

        # разбор
        zl = zone_lums(im)
        theme, cr = choose_theme(zl, OVERLAY_PHOTO_DARK, OVERLAY_PHOTO_LIGHT)
        px = im.convert("RGB").resize((64, 36)).load()
        acc = [0, 0, 0]
        for yy in range(36):
            for xx in range(64):
                r, g, b = px[xx, yy]
                acc[0] += r; acc[1] += g; acc[2] += b
        bg = tuple(v // (64 * 36) for v in acc)

        meta[out_path.name] = {
            "source": p.name,
            "width": im.width,
            "height": im.height,
            "aspect": round(im.width / im.height, 3),
            "source_aspect": src_ar,
            "bytes": out_path.stat().st_size,
            "bg_color": hexc(bg),
            "theme": theme,
            "text_color": TEXT_COLOR[theme],
            "accent_color": ACCENT[theme],
            "shading": SHADING[theme],
            "zone_lums": {k: round(v, 3) for k, v in zl.items()},
            "contrast_worst": round(cr[theme]["score"], 2),
            "note": "фоновый пул канала (материал владельца) - брендированная "
                    "заставка, внешняя атрибуция не требуется",
        }
        print(f"ok {out_path.name}: {im.width}x{im.height}, bg {hexc(bg)}, "
              f"theme {theme}, text {TEXT_COLOR[theme]}, "
              f"{out_path.stat().st_size // 1024} KB")
        if a.delete:
            p.unlink()

    META.write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    print(f"meta: {META} ({len(meta)} images)")


if __name__ == "__main__":
    main()
