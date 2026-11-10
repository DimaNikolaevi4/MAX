# MAX — методика ведения каналов в MAX и Telegram

Репозиторий — это **методика ведения нескольких каналов** через Bot API: MAX —
основная площадка, Telegram — закрывающийся канал `tg_neuro`. Проект
спроектирован так, чтобы с ним одинаково комфортно работал любой ИИ-агент:
локальный (OpenCode и подобные) или онлайн. Агент готовит посты, изучает архив
опубликованных материалов для соблюдения стиля канала, отправляет их через
Bot API и коммитит результат в git.

Главный документ для агента — **`AGENTS.md`**: методика, правила, ограничения.
Этот файл — обзор для человека.

## Роли бота

Бот AI Now (`@se14808890_bot`) и методика разделены на три независимые роли:

| Роль | Папка | Что делает |
| --- | --- | --- |
| **Архивариус** | `roles/archivist/` | личные фото и видео → приватный «архив изображения»; в каналы блогера не публикует |
| **Блогер** | `roles/blogger/` | посты в каналы MAX и Telegram. Согласование постов — в рабочем чате с агентом, не в MAX |
| **Новостной бот** | `roles/newsbot/` | личные дайджесты по расписанию. Единственная роль, которой разрешён диалог с ботом |

Общее для всех ролей — `shared/`: `paths.py` (пути репозитория), `post_guard.py`
(запрет публикации в диалоги и группы), `text_check.py` (орфография и
пунктуация через LanguageTool), `verify_layout.py` (проверка структуры).
Личный диалог бота закреплён за новостным ботом; публикация в него остальным
запрещена — см. `docs/bot-publications-archive.md`.

## Каналы

Реестр — `roles/blogger/config/channels.json` (токенов там нет). Папка канала:
`roles/blogger/channels/<slug>/`.

| slug | площадка | канал | назначение |
| --- | --- | --- | --- |
| `ainow` | MAX | AI — https://max.ru/channel_ainow | основной: нейросети, промпты, кейсы |
| `na100` | MAX | Нейросети и ИИ | закрывается, подписчики переливаются в `ainow` |
| `administrator` | MAX | Администрирование каналов | закрывается, перелив в `ainow` |
| `ozon_group` | MAX | Ozon Находки | под удаление 12.11.2026: публикация не ведётся, храним только дату |
| `zabava` | MAX | Забавное — https://max.ru/channel_zabava | юмор, короткие видео |
| `tg_neuro` | Telegram | Нейро Мульт Студия — https://t.me/Neuro_Animation_Studio | закрывается, перелив в `ainow` |

У закрывающихся каналов призыв (CTA) ведёт на основной канал `ainow`
(`cta_label`/`cta_url` в реестре). У `ainow` и `zabava` — на себя.

## Карта репозитория

```
MAX/
├── AGENTS.md                 # методика и правила для ИИ-агентов (главный файл)
├── README.md                 # этот файл
├── docs/                     # 9 документов методики
│   ├── bot-setup.md              # настройка бота с нуля (проверено на практике)
│   ├── agent-onboarding.md       # вход для нового ИИ-агента
│   ├── blogger-ainow-prompt.md   # промт ИИ-блогера канала AI
│   ├── layout-verification.md    # что проверяет shared/verify_layout.py
│   ├── scheduled-tasks.md        # задачи Планировщика Windows
│   ├── stats-analysis.md         # анализ утренних снимков статистики
│   ├── migration-plan.md         # план миграции закрывающихся каналов
│   ├── closure-2026-11-05.md     # итог закрытия каналов 05.11.2026
│   └── bot-publications-archive.md  # архив методики публикации в личку бота
├── roles/
│   ├── archivist/
│   │   ├── docs/archive-channel.md   # лимиты и схема наполнения архива
│   │   └── tools/                   # archive_plan.py, archive_upload.py,
│   │                                # inbox_batch_*.py, collect_devices.py…
│   ├── blogger/
│   │   ├── bin/                     # post.php (PHP-публикатор) и задачи
│   │   │                            # Планировщика: publish_scheduled.ps1,
│   │   │                            # stats_snapshot.ps1, zabava_publish.ps1
│   │   ├── config/channels.json     # реестр каналов (без токенов)
│   │   ├── channels/<slug>/         # style.md, cta-phrases.json, posts/;
│   │   │                            # proofread.md — статус вычитки (ainow)
│   │   └── tools/                   # 15 инструментов публикации — см. ниже
│   └── newsbot/
│       ├── TASK.md                  # правила и состояние эксперимента
│       └── src/                     # digest_bot.py, brief.py, news_digest.py,
│                                    # send_msg.py, updates_once.py
├── shared/                   # paths.py, post_guard.py, text_check.py, verify_layout.py
├── deploy/tg-relay.php       # релей публикации в Telegram (хостинг 0s3.ru)
├── archive/review.php        # устаревшая методика: отправка в личку бота
├── nev/                      # материалы канала «Нев»: посты и manifest.json
└── local/                    # токены, CA-бандл, логи, статистика, планы
                              # (в git не попадает, кроме tokens.example.json)
```

Картинки и исходники статей (`nev/**/*.docx`, `nev/posting/images/`) в git не
хранятся — только локально, см. `AGENTS.md`, раздел 2в.

## Инструменты блогера

`roles/blogger/tools/`, запуск из корня репозитория.

| Скрипт | Назначение |
| --- | --- |
| `publish_post.py` | пост в канал MAX: текст, обложка (`image_file`), видео (`video_file`/`video_source`), CTA |
| `publish_video.py` | пост с медиа (формат «Забавное»): видео или альбом до 6 фото (`image_files`) |
| `publish_plan.py` | следующий `pending`-пост из плана «Забавного» (`local/zabava-plan.json`) |
| `publish_scheduled.py` | все посты `status: approved` с датой из имени ≤ сегодня (для Планировщика) |
| `publish_telegram.py` | пост в Telegram через релей `deploy/tg-relay.php` |
| `tg_direct.py` | резервная отправка в Telegram напрямую (`--ip`), если релей недоступен |
| `pick_image.py` | подбор картинки из архива AI для поста закрывающегося канала |
| `fetch_images.py` | выгрузка обложек постов AI в локальную библиотеку |
| `make_card.py` | титульная карточка поста — только по прямому указанию владельца |
| `ensure_cta_quote.py` | пакетная правка CTA и текстовые замены в опубликованных постах |
| `build_markdown.py` | сборка текста точными заменами с контролем числа вхождений |
| `markup_fragments.py` | снятие фрагментов разметки из ответа `GET /messages` (UTF-16) |
| `delete_post_by_slug.py` | удаление поста канала по короткому URL |
| `stats_snapshot.py` | снимок статистики: подписчики, просмотры, прирост |
| `zabava_random_plan.py` | случайный старый видео-пост «Забавного» → в план публикации |

## Формат поста

Каждый пост — отдельный Markdown-файл с front matter:

```markdown
---
channel: ainow            # slug канала: совпадает с папкой и с --channel
status: draft             # draft -> approved -> published
format: markdown          # markdown | html
notify: true              # push-уведомления (для каналов должно быть true)
image_file: local/images/ainow/2026-11-10/cover.png   # обложка (необязательно)
video_file: local/video/zabava/AaE61N2beGI-1.mp4       # видео вместо обложки
video_source: zabava:AaHDr80pbqA                        # или взять видео из поста-источника
image_files: "путь1.png | путь2.png"                    # альбом до 6 фото
cta_label: AI                                           # переопределение призыва
cta_url: https://max.ru/channel_ainow
spell_ignore: "слово, ещё-слово"                        # не считать ошибками
published_at: null        # поля ниже дописывают скрипты, вручную не заполнять
message_id: null
channel_id: null
url: null
views: null
edited_at: null
---

Текст поста...
```

Служебные поля (`published_at`, `message_id`, `channel_id`, `url`, `views`,
`edited_at`, `media_count`, `images`, `imported`) заполняют публикаторы и
скрипты статистики. Поле `status` читают все публикаторы: `published` —
повторно не отправляется.

Статусы (жизненный цикл):

- `draft` — черновик, публике не виден, бот его **не отправит**;
- `approved` — человек подтвердил публикацию, Планировщик может отправлять;
- `published` — отправлено, файл хранится как архив с ID и ссылкой.

## Как опубликовать пост

### PHP (хостинг или машина с PHP 8.1+ и curl)

```bash
php roles/blogger/bin/post.php roles/blogger/channels/ainow/posts/<файл>.md
php roles/blogger/bin/post.php <файл> --dry-run          # показать payload, не отправляя
php roles/blogger/bin/post.php <файл> --chat-id=123456   # временно переопределить chat_id
```

Переменные окружения PHP-публикатора: `MAX_TOKENS_FILE` (по умолчанию
`local/tokens.json`), `MAX_API_BASE` (по умолчанию `https://platform-api2.max.ru`),
`MAX_CA_CERT` (CA-сертификат, например Минцифры), `MAX_INSECURE=1` (отключить
проверку TLS — только для отладки).

### Python (рабочая машина на Windows)

```powershell
$env:MAX_HTTP='python'
$env:MAX_CA_CERT=(Resolve-Path local/russian_ca_bundle.pem).Path
py roles/blogger/tools/publish_post.py --channel ainow roles/blogger/channels/ainow/posts/<файл>.md
```

`MAX_HTTP=python` переводит транспорт на stdlib urllib: TLS curl/schannel не
принимает российские цепочки сертификатов CDN `iu.oneme.ru` (см. AGENTS.md,
раздел 5). `MAX_CA_CERT` — бандл «корень + промежуточный Минцифры»
(`local/russian_ca_bundle.pem`), добавляется в доверие и к `--cacert` для curl.
`MAX_INSECURE=1` — отключить проверку TLS (только отладка).

### Пост с медиа

```powershell
py roles/blogger/tools/publish_video.py --channel zabava --dry-run roles/blogger/channels/zabava/posts/<файл>.md
py roles/blogger/tools/publish_video.py --channel zabava <файл>.md
```

Видео берётся из `video_file` (или `--video <файл>`), альбом — из `image_files`
(до 6 фото). Если файла нет на машине, `video_source: <канал>:<mid>` заставляет
публикатор скачать видео из поста-источника.

### План «Забавного»

```powershell
py roles/blogger/tools/publish_plan.py --status
py roles/blogger/tools/publish_plan.py --dry-run
py roles/blogger/tools/publish_plan.py
```

Берётся первый `pending`-пост из `local/zabava-plan.json`; интервалов и дневных
лимитов нет — публикуется всё, что готово.

### Telegram (`tg_neuro`)

```powershell
py roles/blogger/tools/publish_telegram.py --channel tg_neuro roles/blogger/channels/tg_neuro/posts/<файл>.md
```

Транспорт — POST на релей `deploy/tg-relay.php` (хостинг 0s3.ru): api.telegram.org
из локальной среды недоступен. Резервный путь при недоступном релее —
`tg_direct.py --ip <IP>`. Под постом ставится inline-кнопка (`button_url` из
front matter или `cta_url` канала).

## Планировщик Windows

Задачи работают под текущим пользователем (ПК выключен — запуск пропускается,
при следующем входе срабатывает `StartWhenAvailable`). Вне окна 07:00–10:00
публикатор ничего не делает, чтобы догоняющий запуск не вышел днём.

| Задача | Когда (МСК) | Что делает |
| --- | --- | --- |
| `MAX stats snapshot` | 07:00 | снимок подписчиков и просмотров ainow и zabava |
| `MAX ainow - publish approved` | 07:15 | публикует посты `status: approved` с датой ≤ сегодня |
| `MAX zabava - publish plan` | 07:16 | публикует `pending`-посты из `local/zabava-plan.json` |

Настройка задач и логи — `docs/scheduled-tasks.md`, `local/logs/`.
`publish_scheduled.py` перед публикацией делает `git fetch` и отказывается
работать, если `origin/main` ушёл вперёд: сначала `git pull --rebase`.

## Статистика

`stats_snapshot.py` снимает подписчиков и просмотры постов, кладёт
`local/stats/<канал>-<дата>.json` и сравнивает с предыдущим снимком. Выводы —
`docs/stats-analysis.md`. Сырые данные в git не попадают.

## Проверка текста и структуры

- `shared/text_check.py` — орфография, пунктуация и грамматика через публичный
  API LanguageTool; публикаторы вызывают его перед отправкой. Слова из
  `spell_ignore` в посте не считаются ошибками.
- `shared/verify_layout.py` — проверка структуры после переносов и
  переименований: пути, конфиги, компиляция, безопасные прогоны. Норма — 0
  ошибок, 0 предупреждений. Описание — `docs/layout-verification.md`.

## Правила безопасности

1. **Токены и ключи никогда не попадают в git.** Храним локально в
   `local/tokens.json` (скопируйте из `local/tokens.example.json`), путь закрыт
   `.gitignore`.
2. Публикация только в каналы (`chat_id < 0`). Диалоги и группы запрещены —
   сторож `shared/post_guard.py`, архив старой методики — `archive/review.php`
   и `docs/bot-publications-archive.md`.
3. Для GitHub Actions токен кладём в Secrets репозитория, а не в файл.

## Ограничения API MAX

- Домен: `https://platform-api2.max.ru`, токен в заголовке `Authorization`
  (не в query-параметрах).
- Лимит: **не более 2 сообщений в секунду** в один канал. Лимит редактирования
  тот же — при массовой правке ставьте паузу 0,5–1 сек на пост.
- Лимит текста поста: **4000 символов**.
- В каналы отправка только с `notify = true` (или без параметра).
- Отложенной публикации в API нет — расписание делает внешний Планировщик
  (раздел выше), а не сам API.
- Загрузка изображения: `POST /uploads?type=image` → одноразовый URL → загрузка
  файла → токен вложения в `POST /messages`. На Windows надёжнее
  `MAX_HTTP=python` (TLS к `iu.oneme.ru`).
- Видео: `POST /uploads?type=video`; пока `attachment.not.ready`, публикатор
  повторяет отправку. Видео заменяет обложку.

Стратегия отладки: сначала `--dry-run`, затем отправка. Подробности и
постмортемы — `AGENTS.md`.
