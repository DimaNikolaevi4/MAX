# Планировщик Windows: календарь блогера (07:20 МСК).
# Что делает: собирает docs/blogger-calendar.md — публикации за 30 дней,
# план на ближайшие дни, удаления — и коммитит/пушит файл.
# Логи — local/logs/.
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath 'E:\github\MAX'
$OutputEncoding = [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$env:PYTHONIOENCODING = 'utf-8'

New-Item -ItemType Directory -Force -Path 'local\logs' | Out-Null
$log = 'local\logs\calendar.console.log'

# Вне утреннего окна не работаем: StartWhenAvailable может догнать пропущенный
# запуск днём, а календарь должен отражать именно утреннее состояние.
$now = Get-Date
if ($now.Hour -lt 7 -or $now.Hour -ge 10) {
    "вне утреннего окна 07:00-10:00, запуск пропущен: $(Get-Date -Format 'dd.MM HH:mm:ss')" |
        Out-File -Append -Encoding UTF8 $log
    exit 0
}

& py 'roles\blogger\tools\build_calendar.py' --push 2>&1 |
    Out-File -Append -Encoding UTF8 $log
& py 'roles\blogger\tools\export_plan.py' 2>&1 |
    Out-File -Append -Encoding UTF8 $log
& py 'E:\github\Календарь\drop.py' 'MAX' 2>&1 |
    Out-File -Append -Encoding UTF8 $log
exit $LASTEXITCODE
