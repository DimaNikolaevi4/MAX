# Планировщик Windows: опрос /updates личного новостного бота (каждые 15 мин).
# digest_bot.py poll — ЕДИНСТВЕННЫЙ консьюмер /updates: события доставляются
# один раз, любые другие вызовы (зонды, снапшот) украдут их у бота.
# Лог: local/logs/pnews-poll.log
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath 'E:\github\MAX'
$OutputEncoding = [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$env:PYTHONIOENCODING = 'utf-8'

New-Item -ItemType Directory -Force -Path 'local\logs' | Out-Null
$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
& py 'roles\newsbot\src\digest_bot.py' poll 90 2>&1 |
    ForEach-Object { "[$stamp] $_" } |
    Out-File -Append -Encoding UTF8 'local\logs\pnews-poll.log'
exit $LASTEXITCODE
