# Планировщик Windows: детерминированная сборка выпуска na100 (06:30 МСК).
# Обёртка digest_build.py: утреннее окно + логи. Логи — local/logs/.
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath 'E:\github\MAX'
$OutputEncoding = [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$env:PYTHONIOENCODING = 'utf-8'

New-Item -ItemType Directory -Force -Path 'local\logs' | Out-Null

# «Только утром»: StartWhenAvailable может догнать пропущенный запуск при
# включении ПК днём. Вне окна 06:00-10:00 ничего не делаем.
$now = Get-Date
if ($now.Hour -lt 6 -or $now.Hour -ge 10) {
    "вне утреннего окна 06:00-10:00, запуск пропущен: $(Get-Date -Format 'dd.MM HH:mm:ss')" |
        Out-File -Append -Encoding UTF8 'local\logs\digest-build-na100.console.log'
    exit 0
}

& py 'roles\blogger\tools\digest_build.py' --channel na100 2>&1 |
    Out-File -Append -Encoding UTF8 'local\logs\digest-build-na100.console.log'
exit $LASTEXITCODE
