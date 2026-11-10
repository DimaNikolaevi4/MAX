# Планировщик Windows: снимок статистики каналов ainow и zabava (07:00 МСК).
# Отчёты — local/stats-report-<канал>.txt, снимки — local/stats/, лог — local/logs/.
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath 'E:\github\MAX'
$OutputEncoding = [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$env:PYTHONIOENCODING = 'utf-8'

New-Item -ItemType Directory -Force -Path 'local\logs' | Out-Null

# «Только утром»: StartWhenAvailable может догнать пропущенный запуск при
# включении ПК днём. Дневной снимок исказил бы отчёт «за сутки», поэтому
# вне утреннего окна (07:00-10:00) ничего не делаем.
$now = Get-Date
if ($now.Hour -lt 7 -or $now.Hour -ge 10) {
    "вне утреннего окна 07:00-10:00, запуск пропущен: $(Get-Date -Format 'dd.MM HH:mm:ss')" |
        Out-File -Append -Encoding UTF8 'local\logs\stats.console.log'
    exit 0
}

$failed = 0
foreach ($channel in @('ainow', 'zabava')) {
    & py 'roles\blogger\tools\stats_snapshot.py' --channel $channel 2>&1 |
        Out-File -Append -Encoding UTF8 'local\logs\stats.console.log'
    if ($LASTEXITCODE -ne 0) { $failed = $LASTEXITCODE }
}
exit $failed
