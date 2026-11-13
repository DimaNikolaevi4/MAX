# Планировщик Windows: публикация постов «Забавного» (07:16 МСК, на минуту
# позже ainow, чтобы git-push каналов не сталкивались).
# Шаг 1: zabava_random_plan.py выбирает случайный старый пост (видео/фото +
#        текст, без призыва), скачивает медиа и добавляет его в план pending
#        (только если pending в плане ещё нет).
# Шаг 2: publish_plan.py публикует ПЕРВЫЙ pending-пост и удаляет старый
#        оригинал. Правило 13.11.2026 (владелец): план можно заполнять на
#        несколько дней вперёд — за один утренний запуск выходит только ОДИН
#        пост (никаких циклов; следующий pending уйдёт завтра в это же время).
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath 'E:\github\MAX'
$OutputEncoding = [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$env:PYTHONIOENCODING = 'utf-8'
$env:MAX_HTTP = 'python'
$ca = 'E:\github\MAX\local\russian_ca_bundle.pem'
if (Test-Path -LiteralPath $ca) { $env:MAX_CA_CERT = $ca }

New-Item -ItemType Directory -Force -Path 'local\logs' | Out-Null
$log = 'local\logs\zabava-publish.console.log'

# «Только утром»: StartWhenAvailable может догнать пропущенный запуск при
# включении ПК днём. Вне утреннего окна (07:00-10:00) ничего не делаем.
$now = Get-Date
if ($now.Hour -lt 7 -or $now.Hour -ge 10) {
    "вне утреннего окна 07:00-10:00, запуск пропущен: $(Get-Date -Format 'dd.MM HH:mm:ss')" |
        Out-File -Append -Encoding UTF8 $log
    exit 0
}

$planPath = 'local\zabava-plan.json'

& py 'roles\blogger\tools\zabava_random_plan.py' 2>&1 |
    Out-File -Append -Encoding UTF8 $log

# Один pending за запуск: при заполненном на несколько дней плане
# zabava_random_plan.py сам не добавит новый (pending уже есть),
# а publish_plan.py опубликует только первый пост из очереди.
& py 'roles\blogger\tools\publish_plan.py' 2>&1 |
    Out-File -Append -Encoding UTF8 $log
exit $LASTEXITCODE
