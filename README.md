# MAX — методика ведения каналов в MAX и Telegram

Репозиторий — методика ведения каналов через Bot API MAX и релей Telegram.
Главный нормативный документ — `AGENTS.md` (особенно §0 FORMAT CORE v1).
Этот файл — обзор для человека, не источник правил.

## Каналы и профили

Реестр — `roles/blogger/config/channels.json` (токенов там нет). Поля профиля:
`format_profile` (`core|zabava|telegram`), `cta_target_mode` (`self|alternate`),
лимиты медиа, длины, реакций и окно догона `publish_window`
(`[start_hour,end_hour]` или `null`). Конкретные времена слотов — только в
`docs/scheduled-tasks.md`.

| Канал | Профиль | Статус | Слот | CTA |
| --- | --- | --- | --- | --- |
| `ainow` | core | активен | 12:00 (Format 1), 21:30 (план) | self |
| `na100` | core | активен, агент готовит утром и публикует прямо в канал | ориентир 07:30 | чередование self ↔ ainow |
| `catden` | core | активен | 20:00 | self |
| `administrator` | core | активен, перезапуск 20.11 | 09:00 вт/чт | чередование self ↔ ainow |
| `zabava` | zabava | активен | обычно 1 пост/сутки, 19:30 | self, призыв без кавычек |
| `tg_neuro` | telegram | активен, миграция аудитории в ainow | по команде | ainow, inline-кнопка |
| `ozon_group` | — | удалён 12.11 | — | — |

Ядро формата действует только на посты с `format_core: 1`; существующие посты
без поля — legacy и не переписываются массовой доводкой. `zabava` и `tg_neuro`
имеют канонические исключительные стили.

## Перелинковка

- `ainow` — 1–2 ссылки на прошлые посты канала.
- `catden` — ровно 1 ссылка на прошлый пост канала.
- `na100` — 0 внешних ссылок, кроме CTA.
- `administrator` — 0–1 ссылка на `ainow`.
- `tg_neuro` — минимум 1 ссылка на конкретный опубликованный пост `ainow`.

## Карта репозитория

```
MAX/
├── AGENTS.md                  # §0 FORMAT CORE v1 — главный формат
├── README.md                  # этот файл (обзор)
├── docs/
│   ├── methodology/           # методологии каналов, в т.ч. channels-classification.md
│   ├── agent-onboarding.md    # вход для агента
│   ├── blogger-calendar.md    # календарь (обновляет агент по просьбе)
│   ├── scheduled-tasks.md     # слоты хостинг-крона (единственный источник)
│   ├── stats-analysis.md      # выводы по статистике
│   ├── catden-*.md            # план, медиа-манифест, execution playbook
│   └── archive/               # устаревшие протоколы, не нормативно
├── roles/blogger/
│   ├── channels/<slug>/       # style.md, cta-phrases.json, posts/, digests/
│   ├── config/channels.json   # реестр каналов и параметры формата
│   └── tools/                 # 31 инструмент — см. ниже
├── shared/                    # format_core.py, paths.py, post_guard.py, verify_layout.py
├── deploy/                    # рабочие копии post_cron.php / stats_cron.php / tg-relay.php
├── tests/                     # test_format_core.py (29 тестов единого движка)
├── local/                     # токены, CA, логи, медиа, временные отчёты (gitignored)
└── archive/                   # устаревшие скрипты
```

## Инструменты блогера (28 строк, 31 скрипт)

| Скрипт | Назначение |
| --- | --- |
| `publish_post.py` | Пост в MAX: текст, image_file/image_files, видео, CTA |
| `check_post.py` | Проверка поста единым движком: `--channel <slug> <post.md> [--core]` |
| `publish_video.py` | Публикация с видео/фото (канон zabava) |
| `publish_plan.py` | Следующий pending-пост из local/zabava-plan.json |
| `publish_scheduled.py` | Все approved-посты с датой ≤ сегодня |
| `publish_telegram.py` | Пост в Telegram через релей |
| `tg_direct.py` | Резервная отправка в Telegram напрямую |
| `digest_build.py` | Детерминированная сборка дайджеста na100 |
| `digest_cover*.py` | Три скрипта обложек: digest_cover, digest_cover_photo, digest_cover_video |
| `digest_polish.py` | Чек-лист выпуска na100 |
| `pick_fallback.py` | Выбор фона из пула na100 |
| `cover_theme.py` | Тема/контраст для обложек |
| `pick_image.py` | Подбор изображения из архива AI |
| `fetch_images.py` | Выгрузка обложек AI в локальную библиотеку |
| `make_card.py` | Титульная карточка — только по прямой команде владельца |
| `ensure_cta_quote.py` | Пакетные правки CTA |
| `build_markdown.py` | Сборка текста точными заменами |
| `markup_fragments.py` | Фрагменты разметки из GET /messages |
| `delete_post_by_slug.py` | Удаление поста по короткой ссылке |
| `stats_snapshot.py` | Снимок подписчиков и просмотров |
| `build_calendar.py` | Сборка docs/blogger-calendar.md |
| `lexicon_calibrate.py`, `pool_add.py` | Калибровка штампов и пул обложек |
| `ainow_polish.py` | Чек-лист поста ainow |
| `media_aspect.py` | Проверка пропорций медиа |
| `plan_rhythm.py` | Проверка ритма пар «альбом → пост» |
| `admin_digest_build.py` | Пост «Цифра недели» для administrator |
| `export_plan.py` | Экспорт плана в канал-календарь |
| `zabava_random_plan.py` | Рандом-повтор старого ролика в план |

Запуск — из корня репозитория, `py roles/blogger/tools/<скрипт>.py`.

## Front matter поста

```yaml
channel: ainow            # slug канала
status: draft             # draft -> approved -> published
format: markdown
notify: true
format_core: 1            # ядро §0; только для новых постов core-каналов
cta_target: self          # self | ainow — для na100/administrator
reactions: true           # факт авто-блока реакций, пишется публикатором
publish_time: 09:00       # МСК; слот поста, если отличается от слота канала
hold: причина             # пауза до прямой команды владельца
image_file: local/images/ainow/.../cover.png
video_file: local/video/zabava/....mp4
spell_ignore: "слово, ещё-слово"
```

`published_at`, `message_id`, `channel_id`, `url`, `views`, `edited_at`,
`media_count`, `images` дописывают публикаторы и статистика. `draft` без «ок»
не публикуется; `published` повторно не отправляется.

## Публикация и отложенные слоты

API MAX не умеет отложенную отправку — расписание делает хостинговый cron.
Единственная таблица слотов — `docs/scheduled-tasks.md`: ainow 12:00
(кросс-пост Format 1) и 21:30, catden 20:00, zabava 19:30,
статистика 07:45. na100 агент готовит утром и публикует прямо в канал
(ориентир 07:30); в `post_cron.php` его нет.
**Format 1** — кросс-пост `ainow` в 12:00 с полем `publish_time` во front matter
(не особый формат текста, пост подчиняется §0). Дата поста — именем файла.
Локальные задачи Windows удалены полностью. Действуют только:
хостинг-автопост, личные правки владельца и действия агента по его прямой
просьбе. Старые и уже подготовленные посты под новый канон не переделываются.

Рабочие копии хостинг-скриптов лежат в `deploy/` (подробности — `deploy/README.md`):
`post_cron.php`, `stats_cron.php`, `tg-relay.php`. Правила формата в PHP-кроне —
подмножество `shared/format_core.py`; при расхождении главнее `AGENTS.md §0`.

## Статистика и проверки

Актуальные снимки собирает `stats_cron.php` на хостинге в
`/0s3/blogger-data/stats/`; сводные отчёты — `docs/stats-analysis.md`.

- `py shared/format_core.py` не запускается напрямую — единая точка входа
  `py roles/blogger/tools/check_post.py --channel <slug> <post.md> [--core]`;
  отчёт пишется в `local/format-core-check-<slug>.txt`.
- `py -m unittest discover -s tests -p "test_*.py"` — 29 тестов формата.
- `py shared/verify_layout.py` — норма 0 ошибок, 0 предупреждений.
- `shared/text_check.py` — LanguageTool, канальные чекеры перечислены в `style.md`.

## Безопасность

1. Токены и ключи — только в gitignored `local/tokens.json`.
2. Публикация только в каналы (`chat_id < 0`); диалоги запрещены.
3. Соседние репозитории (`kalendar`, `Konkurs`, `vol`, `cross-autoposting`) — вне
   скоупа без отдельной прямой команды владельца.
