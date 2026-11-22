# Регистрация задач Планировщика Windows для каналов проекта.
# ВНИМАНИЕ (правило владельца 13.11.2026): задачи живут ТОЛЬКО на домашней
# машине. На рабочей машине задач Планировщика для этого репозитория быть
# не должно; если скрипт запущен там по ошибке — удалить:
#   Get-ScheduledTask -TaskName 'MAX*' | Unregister-ScheduledTask -Confirm:$false
# Идемпотентно: повторный запуск перезаписывает задачи с теми же именами.
# Запуск: powershell -NoProfile -ExecutionPolicy Bypass -File roles\blogger\bin\register_tasks.ps1
# Перерегистрировать только часть задач: ... register_tasks.ps1 -Only 'MAX stats snapshot','MAX na100 - publish approved'
#
# АКТИВНЫ только три локальные задачи: na100 build 06:30, blogger calendar 07:20,
# na100 publish 07:30. Задачи ainow 07:15, stats 07:00, zabava 19:30 и catden
# регистрируются ЯВНО ОТКЛЮЧЁННЫМИ: публикация на хостинге (post_cron.php),
# статистика — stats_cron.php (07:45). Включение ainow 07:15 даст дубль с
# хостингом — этого нельзя допускать (комментарий «публикация на хостинге»).
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

# имя задачи, время, скрипт-обёртка, Disabled (true = публикация на хостинге)
$tasks = @(
    @{ Name = 'MAX na100 - build digest';      At = '06:30'; File = 'digest_build_na100.ps1';     Disabled = $false },
    @{ Name = 'MAX stats snapshot';            At = '07:00'; File = 'stats_snapshot.ps1';         Disabled = $true },  # публикация на хостинге; статистика — stats_cron.php (07:45)
    @{ Name = 'MAX ainow - publish approved';  At = '07:15'; File = 'publish_scheduled.ps1';      Disabled = $true },  # публикация на хостинге (post_cron.php 12:00/21:30); включение даст дубль
    @{ Name = 'MAX zabava - publish plan';     At = '19:30'; File = 'zabava_publish.ps1';         Disabled = $true },  # публикация на хостинге (post_cron.php 19:30)
    # MAX catden - publish approved: локальная задача не регистрируется — публикация на хостинге (post_cron.php 07:32/20:00)
    @{ Name = 'MAX blogger calendar';          At = '07:20'; File = 'calendar_update.ps1';        Disabled = $false },
    @{ Name = 'MAX na100 - publish approved';  At = '07:30'; File = 'publish_scheduled_na100.ps1'; Disabled = $false }
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
    # -Disabled обязателен: -Force перезаписывает задачу и снимал бы флаг отключения
    # у ainow 07:15 — запуск воскресил бы локальную публикацию и дал дубль с хостингом.
    $reg = @{
        TaskName    = $t.Name
        Action      = $action
        Trigger     = $trigger
        Settings    = $settings
        Principal   = $principal
        Description = 'Публикации каналов MAX (см. docs/scheduled-tasks.md)'
        Force       = $true
    }
    if ($t.Disabled) { $reg['Disabled'] = $true }
    Register-ScheduledTask @reg | Out-Null
    if (-not $t.Disabled) { $registered++ }

    $info = Get-ScheduledTask -TaskName $t.Name | Get-ScheduledTaskInfo
    '{0,-28} {1}  state={2}  next={3}' -f $t.Name, $t.At, (Get-ScheduledTask -TaskName $t.Name).State, $info.NextRunTime
}

'готово: активных локальных задач {0} (остальные отключены: публикация на хостинге)' -f $registered
