# -*- coding: utf-8 -*-
"""Заставка «paper» (мачхед + панель «ФОРМАТ») поверх видео-фона (ffmpeg).

Методика заставок канала na100: roles/blogger/channels/na100/cover-method.md.
Накладывает те же элементы, что digest_cover_photo.py, но на видеофайл:
текст через drawtext (textfile), подложки через drawbox. Звук сохраняется.

Использование:
  python roles/blogger/tools/digest_cover_video.py --src <фон.mp4> --out <файл.mp4> \
      [--theme light|dark] [--items "a|b|c|d|e"] [--sub "итоги суток"]

ffmpeg берётся из пакета imageio-ffmpeg (pip install imageio-ffmpeg) —
системного ffmpeg на машинах может не быть.

Грабли, на которые потрачено время 11.11 (не повторять):
  * drawtext-пути в filtergraph не должны содержать ':' и кириллицы —
    шрифт и textfile копируются во временную папку и используются по
    коротким именам, ffmpeg запускается с cwd=эта папка;
  * текстовые файлы для textfile пишутся с newline="\n": Windows-запись
    по умолчанию ставит "\r\n", а drawtext трактует "\r" как ещё один
    перенос строки (строка уезжала вниз и наезжала на подзаголовок).

Проверено 11.11.2026: пост https://max.ru/channel_na100/AaHI4ZuyEec
(светлое видео 1920x1080, theme light).
"""
import argparse
import imageio_ffmpeg
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import mkdtemp
from PIL import Image
from cover_theme import (aspect_info, fit_text_block, release_stamp, resolve_theme,
                         ASPECT_TOL, OVERLAY_VIDEO_DARK, OVERLAY_VIDEO_LIGHT)

FONT = r"C:\Windows\Fonts\segoeuib.ttf"    # Segoe UI Bold
FONT_SB = r"C:\Windows\Fonts\seguisb.ttf"  # Segoe UI Semibold
MSK = timezone(timedelta(hours=3))

NAVY = "0x16305E"
GREEN_DARK = "0x1F9D66"   # акцент на светлом фоне
GREEN = "0x3EDB9A"        # акцент на тёмном фоне
GRAY_LIGHT = "0x4A6E8C"   # футер на светлом фоне
GRAY_DARK = "0x8FB8C8"    # футер на тёмном фоне

# геометрия для 1920x1080
LX = 96
PX1, PX2 = 1100, 1824
RX = 1150
TX = 1245


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="фоновое видео (mp4)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--theme", choices=["auto", "light", "dark"], default="auto",
                    help="auto — тема по первому кадру (контраст, худшая зона)")
    ap.add_argument("--over", default=None,
                    help="надстрока; по умолчанию — время, дата, день недели выпуска")
    ap.add_argument("--t1", default="Новости")
    ap.add_argument("--t2", default="мира техники")
    ap.add_argument("--sub", default="итоги суток")
    ap.add_argument("--items", default="",
                    help="пункты панели через | (обычно 5 заголовков выпуска)")
    ap.add_argument("--no-date", action="store_true")
    a = ap.parse_args()
    src = str(Path(a.src).resolve())   # ffmpeg работает с cwd=tmp — пути абсолютные
    out = str(Path(a.out).resolve())

    ff = imageio_ffmpeg.get_ffmpeg_exe()

    # кадр для анализа: тема (auto) и проверка 16:9
    tmp = Path(mkdtemp(prefix="cover_video_"))
    shutil.copy(FONT, tmp / "font.ttf")
    shutil.copy(FONT_SB, tmp / "font_sb.ttf")
    frame_png = tmp / "frame.png"
    r0 = subprocess.run([ff, "-y", "-i", src, "-frames:v", "1", "-q:v", "2",
                         str(frame_png)],
                        capture_output=True, timeout=120, cwd=str(tmp))
    if r0.returncode != 0 or not frame_png.exists():
        print(r0.stderr.decode("utf-8", "replace")[-800:])
        raise SystemExit(1)
    frame = Image.open(frame_png)
    ar, rel = aspect_info(frame)
    if abs(rel - 1) > ASPECT_TOL:
        raise SystemExit(f"background video not 16:9: aspect {ar:.3f} "
                         f"({rel:.2f}x), rejected")
    crop = ""
    W0, H0 = frame.size
    if abs(rel - 1) > 0.01:  # подгонка до точных 16:9 до наложения текста
        if rel > 1:
            crop = f"crop={round(H0 * 16 / 9) // 2 * 2}:{H0},"
        else:
            crop = f"crop={W0}:{round(W0 * 9 / 16) // 2 * 2},"
        print(f"aspect {ar:.3f} -> center-crop filter to 16:9")

    theme, auto_note = resolve_theme(a.theme, frame, OVERLAY_VIDEO_DARK,
                                     OVERLAY_VIDEO_LIGHT)
    if auto_note:
        print(auto_note)
    light = theme == "light"
    col_text = NAVY if light else "0xFFFFFF"
    col_green = GREEN_DARK if light else GREEN
    col_blue = GRAY_LIGHT if light else "0x9FC4D4"
    col_gray = GRAY_LIGHT if light else GRAY_DARK
    shadow = "white@0.6" if light else "black@0.45"

    def tf(name: str, text: str) -> Path:
        p = tmp / name
        p.write_text(text, encoding="utf-8", newline="\n")  # БЕЗ \r\n (см. докстринг)
        return p

    # подгонка текста: перенос -> уменьшение кегля -> «…» (правило 11.11,
    # пост AaHI4ZuyEec: пункт 03 вылезал за затенение панели)
    MAST_W = PX1 - LX - 40          # безопасная ширина мачхеда (до панели)
    ITEM_MAX_W = PX2 - 30 - TX      # безопасная ширина пункта внутри панели

    def fit1(text, font_path, start, min_size):
        size, lines, trunc = fit_text_block(text, font_path, MAST_W,
                                            max_lines=1, start=start,
                                            min_size=min_size)
        if trunc:
            print("warning: masthead text truncated to fit")
        return size, lines[0]

    ov_size, over_txt = fit1(a.over or release_stamp(datetime.now(MSK)),
                             FONT_SB, 40, 30)
    t1_size, t1_txt = fit1(a.t1, FONT, 106, 70)
    t2_size, t2_txt = fit1(a.t2, FONT, 106, 70)
    sub_size, sub_txt = fit1(a.sub, FONT_SB, 64, 44)
    foot_size, foot_txt = fit1("max.ru/channel_na100", FONT_SB, 36, 28)

    f_over = tf("over.txt", over_txt)
    f_t1 = tf("t1.txt", t1_txt)
    f_t2 = tf("t2.txt", t2_txt)
    f_sub = tf("sub.txt", sub_txt)
    f_foot = tf("foot.txt", foot_txt)
    f_fmt = tf("fmt.txt", "Ф О Р М А Т")

    raw_items = [s.strip() for s in a.items.split("|") if s.strip()]
    fitted_items = []
    for i, s_txt in enumerate(raw_items, 1):
        size, lines, trunc = fit_text_block(s_txt, FONT, ITEM_MAX_W,
                                            max_lines=2, start=40, min_size=24)
        if trunc:
            print(f"warning: panel item {i} truncated to fit")
        fitted_items.append((size, [tf(f"it{i}_{k}.txt", ln)
                                    for k, ln in enumerate(lines)], len(lines)))

    # вертикальное центрирование мачхеда (решение 11.11.2026): блок
    # название+линия+подзаголовок центрируется между надстрокой и футером —
    # раньше t1/t2 стояли на жёстких y=170/330, название висело высоко
    t1_h = round(t1_size * 1.16)
    t2_h = round(t2_size * 1.16)
    sub_h = round(sub_size * 1.22)
    gap_t2 = 30       # между строками названия
    gap_line = 44     # название -> акцентная линия
    gap_sub = 34      # линия -> подзаголовок
    line_h = 9
    zone_top = 100 + round(ov_size * 1.5)
    zone_bot = 985 - 20
    group_h = t1_h + gap_t2 + t2_h + gap_line + line_h + gap_sub + sub_h
    y_t1 = zone_top + max(0, (zone_bot - zone_top - group_h) // 2)
    y_t2 = y_t1 + t1_h + gap_t2
    y_line = y_t2 + t2_h + gap_line
    y_sub = y_line + line_h + gap_sub

    f = [
        # подложка панели «ФОРМАТ»
        f"drawbox=x={PX1}:y=80:w={PX2 - PX1}:h=940:color="
        + ("white@0.72" if light else "black@0.45") + ":t=fill",
        f"drawbox=x={PX1 + 8}:y=130:w=3:h=840:color={col_gray}@0.55:t=fill",
        # акцентная линия под заголовком
        f"drawbox=x={LX}:y={y_line}:w=230:h={line_h}:color={col_green}:t=fill",
        # мачхед
        f"drawtext=fontfile=font_sb.ttf:textfile={f_over.name}:fontsize={ov_size}:fontcolor={col_gray}:x={LX}:y=100",
        f"drawtext=fontfile=font.ttf:textfile={f_t1.name}:fontsize={t1_size}:fontcolor={col_text}"
        f":x={LX}:y={y_t1}:shadowx=2:shadowy=2:shadowcolor={shadow}",
        f"drawtext=fontfile=font.ttf:textfile={f_t2.name}:fontsize={t2_size}:fontcolor={col_text}"
        f":x={LX}:y={y_t2}:shadowx=2:shadowy=2:shadowcolor={shadow}",
        f"drawtext=fontfile=font_sb.ttf:textfile={f_sub.name}:fontsize={sub_size}:fontcolor={col_green}"
        f":x={LX}:y={y_sub}:shadowx=2:shadowy=2:shadowcolor={shadow}",
        f"drawtext=fontfile=font_sb.ttf:textfile={f_foot.name}:fontsize={foot_size}:fontcolor={col_gray}:x={LX}:y=985",
    ]
    if not a.no_date:
        f.append(f"drawtext=fontfile=font_sb.ttf:text={datetime.now():%d.%m.%Y}"
                 f":fontsize=36:fontcolor={col_gray}:x=w-text_w-{LX}:y=985")

    f.append(f"drawtext=fontfile=font_sb.ttf:textfile={f_fmt.name}:fontsize=34:fontcolor={col_gray}:x={RX}:y=140")
    row_y = 230
    for i, (size, line_files, n_lines) in enumerate(fitted_items, 1):
        f.append(f"drawtext=fontfile=font.ttf:text=0{i}:fontsize=46:fontcolor={col_green}:x={RX}:y={row_y}")
        lh = round(size * 1.15)
        for k, p in enumerate(line_files):
            f.append(f"drawtext=fontfile=font.ttf:textfile={p.name}:fontsize={size}:fontcolor={col_text}"
                     f":x={TX}:y={row_y + 5 + k * lh}:shadowx=1:shadowy=1:shadowcolor={shadow}")
        if i < len(fitted_items):
            f.append(f"drawbox=x={RX}:y={row_y + 118}:w={PX2 - RX - 10}:h=2:color={col_gray}@0.35:t=fill")
        row_y += 158

    ff = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ff, "-y", "-i", src,
        "-vf", crop + ",".join(f),
        "-c:v", "libx264", "-preset", "medium", "-crf", "22",
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        out,
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=900, cwd=str(tmp))
    if r.returncode != 0:
        print(r.stderr.decode("utf-8", "replace")[-1500:])
        raise SystemExit(1)
    print("ok (video-paper)", Path(out).stat().st_size)


if __name__ == "__main__":
    main()
