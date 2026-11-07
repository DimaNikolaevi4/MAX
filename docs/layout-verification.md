# Проверка структуры после разделения ролей (фаза C)

Скрипт: `shared/verify_layout.py`. Запуск из корня репозитория:

```powershell
py shared/verify_layout.py
```

Скрипт ничего не публикует и не меняет: сетевых вызовов нет, `archive_upload.py`
запускается только с `--dry-run --limit 3`. Полный отчёт пишется в
`local/verify-layout.txt`, в консоль выводятся только строки `OK/WARN/FAIL` и
итог. Код возврата: `0` — ошибок нет, `1` — есть хотя бы один `FAIL`.

## Что проверяется

1. **Структура.** На месте ли `roles/archivist`, `roles/blogger`,
   `roles/newsbot`, `shared`; не остались ли старые `tools/`, `bin/`, `config/`,
   `experiments/`, `channels/` в корне; существуют ли ключевые файлы
   (`AGENTS.md`, `roles/blogger/bin/post.php`, `shared/paths.py` и т.д.).
2. **Конфиги.** `roles/blogger/config/channels.json` читается; у каждого канала
   есть папка в `roles/blogger/channels/` и запись с токеном и отрицательным
   `chat_id` в `local/tokens.json`; есть ключ `newsbot`.
3. **Python.** Компиляция всех файлов `roles/` и `shared/`; отсутствие
   устаревшего `REPO = Path(__file__).resolve().parent.parent`; импорт
   `publish_post` (проверяет, что `shared.paths` и `shared.post_guard`
   подключаются).
4. **Безопасные прогоны.** `brief_selftest.py` (10/10), `digest_bot.py
   registry`, `archive_upload.py --dry-run --limit 3`.
5. **Сторож.** Канал (`chat_id < 0`) разрешён, диалоги и группы
   (`537566305`, `0`, `1`) заблокированы.
6. **Устаревшие пути в коде.** Поиск `tools/<name>.py` без роли,
   `bin/post.php`, `config/channels.json`, `experiments/personal-news` и
   `channels/<slug>` без префикса `roles/blogger/`.
7. **Ссылки в документации.** Пути в backticks вида `roles/…`, `shared/…`,
   `docs/…`, `archive/…`, `deploy/…` должны существовать; шаблоны `<slug>`,
   `*` и `{…}` пропускаются.

## Когда запускать

- после переноса или переименования папок и файлов;
- после изменения `shared/paths.py` или путей к `channels/`/`config/`;
- перед коммитом крупного рефакторинга;
- для диагностики «почему скрипт не находит токены/канал».

## Ограничения

- PHP-синтаксис не проверяется, если в системе не установлен `php` (на рабочей
  машине его нет). Пути внутри `post.php` проверяются только глазами и тестами
  публикации.
- Реальная публикация в канал не выполняется — это отдельный цикл из
  `AGENTS.md`, раздел 3.
