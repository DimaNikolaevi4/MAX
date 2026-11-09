# Задачи Планировщика Windows (ainow)

Настроены 09.11.2026. Работают под текущим пользователем, только когда он
в системе (LogonType Interactive): ПК выключен или пользователь не вошёл —
запуск пропускается, при следующем входе сработает `StartWhenAvailable`.

| Задача | Когда (МСК) | Что делает |
|---|---|---|
| `MAX ainow - publish approved` | ежедневно 09:00 и 18:00 | публикует не больше одного поста со `status: approved`, дата из имени файла ≤ сегодня |
| `MAX ainow - stats snapshot` | ежедневно 21:00 | снимает подписчиков и просмотры постов, пишет динамику |

## Публикация: как это устроено

1. Владелец говорит «ок» в рабочем чате.
2. Агент переводит пост из `status: draft` в `status: approved`.
3. В 09:00 или 18:00 задача запускает
   `roles/blogger/tools/publish_scheduled.py`:
   - `git fetch`; если `origin/main` ушёл вперёд — публикация откладывается;
   - проверяет картинку, CTA-цитату и уникальность фразы призыва;
   - публикует через `publish_post.py` (upload, POST, GET-контроль);
   - дописывает CTA-фразу в `cta-phrases.json`;
   - коммитит пост и реестр, делает `git push origin main`;
   - пишет отчёт в `local/scheduled-publish.txt`, лог — `local/logs/`.
4. `draft` без «ок» не публикуется никогда; `published` повторно не берётся.
5. За один запуск — не больше одного поста (`--limit`), защита от
   параллельных запусков — `local/publish-scheduled.lock`.

Ручной запуск и проверка:

```powershell
cd E:\github\MAX
py roles\blogger\tools\publish_scheduled.py --channel ainow --dry-run
py roles\blogger\tools\publish_scheduled.py --channel ainow
```

## Статистика: что снимается

`roles/blogger/tools/stats_snapshot.py` через MAX Bot API берёт:

- `GET /chats/{chat_id}` — подписчики, число сообщений;
- `GET /messages?chat_id=...&count=100` — просмотры каждого поста (`stat.views`).

Пишет:

- `local/stats/ainow-YYYY-MM-DD.json` — снимок дня (один файл на день);
- `local/stats-report.txt` — подписчики и их прирост, новые посты,
  топ прироста просмотров;
- `local/logs/stats.log` — история запусков.

Первый снимок — база, динамика появится со второго дня. Недельная сводка:

```powershell
py roles\blogger\tools\stats_snapshot.py --channel ainow --weekly
```

Ограничения API: нет реакций, охвата, CTR по ссылкам, источников трафика и
истории подписчиков — только просмотры и текущее число участников.
`count=100` — последние 100 сообщений; для канала этого достаточно.

## Управление задачами

```powershell
Get-ScheduledTask -TaskName 'MAX ainow*' | Select-Object TaskName,State
Get-ScheduledTaskInfo -TaskName 'MAX ainow - stats snapshot'
Start-ScheduledTask -TaskName 'MAX ainow - stats snapshot'   # прогнать сейчас
Disable-ScheduledTask -TaskName 'MAX ainow - publish approved'
Enable-ScheduledTask  -TaskName 'MAX ainow - publish approved'
Unregister-ScheduledTask -TaskName 'MAX ainow - publish approved' -Confirm:$false
```

Отчёты после автоматической публикации в чат не приходят: их нужно смотреть
в `local/scheduled-publish.txt` (или запросить у агента в следующей сессии).
