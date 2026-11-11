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
from pathlib import Path
from tempfile import mkdtemp

FONT = r"C:\Windows\Fonts\segoeuib.ttf"    # Segoe UI Bold
FONT_SB = r"C:\Windows\Fonts\seguisb.ttf"  # Segoe UI Semibold

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
    ap.add_argument("--theme", choices=["light", "dark"], default="light")
    ap.add_argument("--over", default="Т Е Х Н О - Д А Й Д Ж Е С Т")
    ap.add_argument("--t1", default="Новости")
    ap.add_argument("--t2", default="мира техники")
    ap.add_argument("--sub", default="итоги суток")
    ap.add_argument("--items", default="",
                    help="пункты панели через | (обычно 5 заголовков выпуска)")
    ap.add_argument("--no-date", action="store_true")
    a = ap.parse_args()

    light = a.theme == "light"
    col_text = NAVY if light else "0xFFFFFF"
    col_green = GREEN_DARK if light else GREEN
    col_blue = GRAY_LIGHT if light else "0x9FC4D4"
    col_gray = GRAY_LIGHT if light else GRAY_DARK
    shadow = "white@0.6" if light else "black@0.45"

    tmp = Path(mkdtemp(prefix="cover_video_"))
    shutil.copy(FONT, tmp / "font.ttf")
    shutil.copy(FONT_SB, tmp / "font_sb.ttf")

    def tf(name: str, text: str) -> Path:
        p = tmp / name
        p.write_text(text, encoding="utf-8", newline="\n")  # БЕЗ \r\n (см. докстринг)
        return p

    f_over = tf("over.txt", a.over)
    f_t1 = tf("t1.txt", a.t1)
    f_t2 = tf("t2.txt", a.t2)
    f_sub = tf("sub.txt", a.sub)
    f_foot = tf("foot.txt", "max.ru/channel_na100")
    f_fmt = tf("fmt.txt", "Ф О Р М А Т")
    item_files = [tf(f"it{i}.txt", s.strip())
                  for i, s in enumerate(a.items.split("|"), 1) if s.strip()]

    f = [
        # подложка панели «ФОРМАТ»
        f"drawbox=x={PX1}:y=80:w={PX2 - PX1}:h=940:color="
        + ("white@0.72" if light else "black@0.45") + ":t=fill",
        f"drawbox=x={PX1 + 8}:y=130:w=3:h=840:color={col_gray}@0.55:t=fill",
        # акцентная линия под заголовком
        f"drawbox=x={LX}:y=522:w=230:h=9:color={col_green}:t=fill",
        # мачхед
        f"drawtext=fontfile=font_sb.ttf:textfile={f_over.name}:fontsize=40:fontcolor={col_gray}:x={LX}:y=100",
        f"drawtext=fontfile=font.ttf:textfile={f_t1.name}:fontsize=106:fontcolor={col_text}"
        f":x={LX}:y=170:shadowx=2:shadowy=2:shadowcolor={shadow}",
        f"drawtext=fontfile=font.ttf:textfile={f_t2.name}:fontsize=106:fontcolor={col_text}"
        f":x={LX}:y=330:shadowx=2:shadowy=2:shadowcolor={shadow}",
        f"drawtext=fontfile=font_sb.ttf:textfile={f_sub.name}:fontsize=64:fontcolor={col_green}"
        f":x={LX}:y=560:shadowx=2:shadowy=2:shadowcolor={shadow}",
        f"drawtext=fontfile=font_sb.ttf:textfile={f_foot.name}:fontsize=36:fontcolor={col_gray}:x={LX}:y=985",
    ]
    if not a.no_date:
        f.append(f"drawtext=fontfile=font_sb.ttf:text={__import__('datetime').datetime.now():%d.%m.%Y}"
                 f":fontsize=36:fontcolor={col_gray}:x=w-text_w-{LX}:y=985")

    f.append(f"drawtext=fontfile=font_sb.ttf:textfile={f_fmt.name}:fontsize=34:fontcolor={col_gray}:x={RX}:y=140")
    row_y = 230
    for i, p in enumerate(item_files, 1):
        f.append(f"drawtext=fontfile=font.ttf:text=0{i}:fontsize=46:fontcolor={col_green}:x={RX}:y={row_y}")
        f.append(f"drawtext=fontfile=font.ttf:textfile={p.name}:fontsize=40:fontcolor={col_text}"
                 f":x={TX}:y={row_y + 5}:shadowx=1:shadowy=1:shadowcolor={shadow}")
        if i < len(item_files):
            f.append(f"drawbox=x={RX}:y={row_y + 118}:w={PX2 - RX - 10}:h=2:color={col_gray}@0.35:t=fill")
        row_y += 158

    ff = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ff, "-y", "-i", a.src,
        "-vf", ",".join(f),
        "-c:v", "libx264", "-preset", "medium", "-crf", "22",
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        a.out,
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=900, cwd=str(tmp))
    if r.returncode != 0:
        print(r.stderr.decode("utf-8", "replace")[-1500:])
        raise SystemExit(1)
    print("ok (video-paper)", Path(a.out).stat().st_size)


if __name__ == "__main__":
    main()
