# Задачи Планировщика Windows (ainow + zabava)

Настроены 09.11.2026, расписание упрощено 10.11.2026: один слот сбора данных и
один слот публикации. Работают под текущим пользователем, только когда он
в системе (LogonType Interactive): ПК выключен или пользователь не вошёл —
запуск пропускается, при следующем входе сработает `StartWhenAvailable`.

| Задача | Когда (МСК) | Что делает |
|---|---|---|
| `MAX stats snapshot` | ежедневно 07:00 | снимает подписчиков и просмотры для ainow и zabava, отчёт за предыдущие сутки |
| `MAX ainow - publish approved` | ежедневно 07:15 | публикует все посты со `status: approved`, дата из имени файла ≤ сегодня |
| `MAX zabava - publish plan` | ежедневно 07:15 | публикует все `pending` посты из `local/zabava-plan.json` |

Ограничений по количеству публикаций в день или неделю и по интервалу между
постами нет: в 07:15 выходит всё, что готово.

## Публикация: как это устроено

1. Владелец говорит «ок» в рабочем чате.
2. Агент переводит пост из `status: draft` в `status: approved`.
3. В 07:15 задача запускает
   `roles/blogger/tools/publish_scheduled.py`:
   - `git fetch`; если `origin/main` ушёл вперёд — публикация откладывается;
   - проверяет картинку, CTA-цитату и уникальность фразы призыва;
   - публикует через `publish_post.py` (upload, POST, GET-контроль);
   - дописывает CTA-фразу в `cta-phrases.json`;
   - коммитит пост и реестр, делает `git push origin main`;
   - пишет отчёт в `local/scheduled-publish.txt`, лог — `local/logs/`.
4. `draft` без «ок» не публикуется никогда; `published` повторно не берётся.
5. Запуск публикует **все** готовые посты (`--limit 0`), защита от
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

Пишет по каждому каналу:

- `local/stats/ainow-YYYY-MM-DD.json`, `local/stats/zabava-YYYY-MM-DD.json` —
  снимок дня (один файл на день);
- `local/stats-report-ainow.txt`, `local/stats-report-zabava.txt` — период
  (предыдущие сутки), прирост подписчиков, новые посты, топ прироста просмотров;
- `local/logs/stats.log` — история запусков.

Задача `MAX stats snapshot` запускает `roles/blogger/bin/stats_snapshot.ps1`,
который последовательно снимает оба канала.

Снимок снимается утром в 07:00, поэтому отчёт покрывает **предыдущие сутки**:
от вчерашнего снимка (07:00) до сегодняшнего. В отчёте это указано строкой
`период: ... → ... (сутки)`. Просмотры в отчёте — прирост за период, а не
накопленные значения.

Порядок в 07:00 важен: снимок идёт **в 07:00**, публикация — **в 07:15**.
Поэтому утренний снимок фиксирует состояние до выхода нового поста, а сам
пост попадает в следующий отчёт уже с просмотрами за полные сутки, а не с
нулём.

Недельная сводка (по каждому каналу отдельно):

```powershell
py roles\blogger\tools\stats_snapshot.py --channel ainow --weekly
py roles\blogger\tools\stats_snapshot.py --channel zabava --weekly
```

Ограничения API: нет реакций, охвата, CTR по ссылкам, источников трафика и
истории подписчиков — только просмотры и текущее число участников.
`count=100` — последние 100 сообщений; для канала этого достаточно.

## «Забавное» (zabava): публикация по плану

- Задача `MAX zabava - publish plan` — ежедневно в **07:15**.
- Запускает `roles/blogger/tools/publish_plan.py`: берёт первый `pending` пост
  из `local/zabava-plan.json` и публикует его. Никаких проверок интервала и
  дневного лимита нет; обёртка повторяет запуск, пока в плане остаются
  `pending` — то есть за один слот уходит всё, что подготовлено.
- Отчёты: `local/publish-plan.txt`, лог — `local/logs/zabava-publish.console.log`.
- Публикует через `publish_video.py`: проверка текста, загрузка медиа, POST,
  GET-контроль, обновление front matter, CTA-фраза дописывается в
  `roles/blogger/channels/zabava/cta-phrases.json`.
- После успеха исходный пост-донор (`source`) удаляется, если в записи плана не
  указано `delete_source: false`.
- Если публикатор вернул ошибку контроля, но пост уже ушёл (front matter
  `status: published`), план всё равно помечается `published` — повторной
  публикации не будет.
- Посты автоматически **не коммитятся**: git по `zabava` остаётся ручным
  решением владельца.

Добавить пост: положить `.md` в `roles/blogger/channels/zabava/posts/`, медиа —
в `local/images/zabava/`, дописать запись в `local/zabava-plan.json` со
`status: pending`. Остановить автопубликацию —
`Disable-ScheduledTask -TaskName 'MAX zabava - publish plan'`.

## Управление задачами

```powershell
Get-ScheduledTask -TaskName 'MAX*' | Select-Object TaskName,State
Get-ScheduledTaskInfo -TaskName 'MAX stats snapshot'
Start-ScheduledTask -TaskName 'MAX stats snapshot'   # прогнать сейчас
Disable-ScheduledTask -TaskName 'MAX ainow - publish approved'
Enable-ScheduledTask  -TaskName 'MAX ainow - publish approved'
Unregister-ScheduledTask -TaskName 'MAX ainow - publish approved' -Confirm:$false
```

Отчёты после автоматических запусков в чат не приходят: публикация —
`local/scheduled-publish.txt`, статистика — `local/stats-report-<канал>.txt`,
план «Забавного» — `local/publish-plan.txt` (или запросить у агента в
следующей сессии).
