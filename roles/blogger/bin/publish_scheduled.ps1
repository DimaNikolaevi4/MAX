# Планировщик Windows: публикация approved-постов ainow.
# Запускается ежедневно в 09:00 и 18:00 (МСК). Логи — local/logs/.
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath 'E:\github\MAX'
$OutputEncoding = [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$env:PYTHONIOENCODING = 'utf-8'

$env:MAX_HTTP = 'python'
$ca = 'E:\github\MAX\local\russian_ca_bundle.pem'
if (Test-Path -LiteralPath $ca) { $env:MAX_CA_CERT = $ca }

New-Item -ItemType Directory -Force -Path 'local\logs' | Out-Null
& py 'roles\blogger\tools\publish_scheduled.py' --channel ainow 2>&1 |
    Out-File -Append -Encoding UTF8 'local\logs\publish-scheduled.console.log'
exit $LASTEXITCODE
