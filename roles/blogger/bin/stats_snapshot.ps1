# Планировщик Windows: снимок статистики ainow + краткий анализ.
# Запускается ежедневно в 21:00 (МСК). Логи — local/logs/.
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath 'E:\github\MAX'
$OutputEncoding = [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$env:PYTHONIOENCODING = 'utf-8'

New-Item -ItemType Directory -Force -Path 'local\logs' | Out-Null
& py 'roles\blogger\tools\stats_snapshot.py' --channel ainow 2>&1 |
    Out-File -Append -Encoding UTF8 'local\logs\stats.console.log'
exit $LASTEXITCODE
