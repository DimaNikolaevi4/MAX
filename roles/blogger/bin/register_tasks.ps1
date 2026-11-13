# Регистрация задач Планировщика Windows для каналов проекта.
# ВНИМАНИЕ (правило владельца 13.11.2026): задачи живут ТОЛЬКО на домашней
# машине. На рабочей машине задач Планировщика для этого репозитория быть
# не должно; если скрипт запущен там по ошибке — удалить:
#   Get-ScheduledTask -TaskName 'MAX*' | Unregister-ScheduledTask -Confirm:$false
# Идемпотентно: повторный запуск перезаписывает задачи с теми же именами.
# Запуск: powershell -NoProfile -ExecutionPolicy Bypass -File roles\blogger\bin\register_tasks.ps1
# Перерегистрировать только часть задач: ... register_tasks.ps1 -Only 'MAX stats snapshot','MAX ainow - publish approved'
#
# Почему не schtasks: /tr чувствителен к кавычкам и кириллице в путях,
# а StartWhenAvailable через schtasks не выставить (см. cover-method.md, «Ловушки»).
#
# Почему через hidden_run.vbs (13.11.2026): при LogonType Interactive прямой
# запуск powershell.exe даже с -WindowStyle Hidden мигает окном консоли на
# каждый старт — особенно заметно на «догонах» StartWhenAvailable (при
# включении ПК все утренние задачи срабатывают разом). wscript.exe —
# GUI-процесс: окна консоли не даёт вообще.
param([string[]]$Only = @())
$ErrorActionPreference = 'Stop'

$repo = 'E:\github\MAX'
$bin = Join-Path $repo 'roles\blogger\bin'
$user = "$env:USERDOMAIN\$env:USERNAME"
$wscript = Join-Path $env:SystemRoot 'System32\wscript.exe'
$hidden = Join-Path $bin 'hidden_run.vbs'

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
$registered = 0

foreach ($t in $tasks) {
    if ($Only -and ($Only -notcontains $t.Name)) { continue }
    $script = Join-Path $bin $t.File
    if (-not (Test-Path -LiteralPath $script)) {
        throw "нет обёртки: $script"
    }
    $action = New-ScheduledTaskAction -Execute $wscript `
        -Argument ('//B //Nologo "{0}" "{1}"' -f $hidden, $script) `
        -WorkingDirectory $repo
    $trigger = New-ScheduledTaskTrigger -Daily -At $t.At
    # ровные секунды: -At берёт текущие секунды, из-за чего старт смещается
    $trigger.StartBoundary = '{0}T{1}:00' -f (Get-Date -Format 'yyyy-MM-dd'), $t.At
    Register-ScheduledTask -TaskName $t.Name -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal -Description 'Публикации каналов MAX (см. docs/scheduled-tasks.md)' `
        -Force | Out-Null
    $registered++

    $info = Get-ScheduledTask -TaskName $t.Name | Get-ScheduledTaskInfo
    '{0,-28} {1}  state={2}  next={3}' -f $t.Name, $t.At, (Get-ScheduledTask -TaskName $t.Name).State, $info.NextRunTime
}

'готово: задач зарегистрировано {0}' -f $registered
