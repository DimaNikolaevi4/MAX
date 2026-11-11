# Регистрация задач Планировщика Windows для каналов проекта.
# Идемпотентно: повторный запуск перезаписывает задачи с теми же именами.
# Запуск: powershell -NoProfile -ExecutionPolicy Bypass -File roles\blogger\bin\register_tasks.ps1
#
# Почему не schtasks: /tr чувствителен к кавычкам и кириллице в путях,
# а StartWhenAvailable через schtasks не выставить (см. cover-method.md, «Ловушки»).
$ErrorActionPreference = 'Stop'

$repo = 'E:\github\MAX'
$bin = Join-Path $repo 'roles\blogger\bin'
$user = "$env:USERDOMAIN\$env:USERNAME"
$ps = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'

# имя задачи, время, скрипт-обёртка
$tasks = @(
    @{ Name = 'MAX na100 - build digest';      At = '06:30'; File = 'digest_build_na100.ps1' },
    @{ Name = 'MAX stats snapshot';            At = '07:00'; File = 'stats_snapshot.ps1' },
    @{ Name = 'MAX ainow - publish approved';  At = '07:15'; File = 'publish_scheduled.ps1' },
    @{ Name = 'MAX zabava - publish plan';     At = '07:16'; File = 'zabava_publish.ps1' },
    @{ Name = 'MAX blogger calendar';          At = '07:20'; File = 'calendar_update.ps1' },
    @{ Name = 'MAX na100 - publish approved';  At = '07:30'; File = 'publish_scheduled_na100.ps1' }
)

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

foreach ($t in $tasks) {
    $script = Join-Path $bin $t.File
    if (-not (Test-Path -LiteralPath $script)) {
        throw "нет обёртки: $script"
    }
    $action = New-ScheduledTaskAction -Execute $ps `
        -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f $script) `
        -WorkingDirectory $repo
    $trigger = New-ScheduledTaskTrigger -Daily -At $t.At
    # ровные секунды: -At берёт текущие секунды, из-за чего старт смещается
    $trigger.StartBoundary = '{0}T{1}:00' -f (Get-Date -Format 'yyyy-MM-dd'), $t.At
    Register-ScheduledTask -TaskName $t.Name -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal -Description 'Публикации каналов MAX (см. docs/scheduled-tasks.md)' `
        -Force | Out-Null

    $info = Get-ScheduledTask -TaskName $t.Name | Get-ScheduledTaskInfo
    '{0,-28} {1}  state={2}  next={3}' -f $t.Name, $t.At, (Get-ScheduledTask -TaskName $t.Name).State, $info.NextRunTime
}

'готово: задач зарегистрировано {0}' -f $tasks.Count
