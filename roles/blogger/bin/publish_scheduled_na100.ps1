# Планировщик Windows: публикация approved-постов na100 (07:30 МСК).
# Логи — local/logs/.
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath 'E:\github\MAX'
$OutputEncoding = [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$env:PYTHONIOENCODING = 'utf-8'

$env:MAX_HTTP = 'python'
$ca = 'E:\github\MAX\local\russian_ca_bundle.pem'
if (Test-Path -LiteralPath $ca) { $env:MAX_CA_CERT = $ca }

New-Item -ItemType Directory -Force -Path 'local\logs' | Out-Null

# «Только утром»: StartWhenAvailable может догнать пропущенный запуск при
# включении ПК днём. Вне утреннего окна (07:00-10:00) ничего не делаем.
$now = Get-Date
if ($now.Hour -lt 7 -or $now.Hour -ge 10) {
    "вне утреннего окна 07:00-10:00, запуск пропущен: $(Get-Date -Format 'dd.MM HH:mm:ss')" |
        Out-File -Append -Encoding UTF8 'local\logs\publish-na100.console.log'
    exit 0
}

& py 'roles\blogger\tools\publish_scheduled.py' --channel na100 2>&1 |
    Out-File -Append -Encoding UTF8 'local\logs\publish-na100.console.log'
exit $LASTEXITCODE
