$ErrorActionPreference = "Stop"

$taskName = "TossAutoTrading-Weekdays"
$projectRoot = Split-Path -Parent $PSScriptRoot
$runScript = Join-Path $PSScriptRoot "run.ps1"
$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$runScript`" run"

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument $arguments `
    -WorkingDirectory $projectRoot

$trigger = New-ScheduledTaskTrigger `
    -Weekly `
    -WeeksInterval 1 `
    -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
    -At "09:04"

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 7) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Toss OpenAPI weekday trading runner; exits itself at PROCESS_STOP_TIME." `
    -Force | Out-Null

Get-ScheduledTask -TaskName $taskName |
    Select-Object TaskName, State
Get-ScheduledTaskInfo -TaskName $taskName |
    Select-Object NextRunTime, LastRunTime, LastTaskResult

$reportTaskName = "TossAutoTrading-DailyReport"
$reportArguments = "-NoProfile -ExecutionPolicy Bypass -File `"$runScript`" report"
$reportAction = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument $reportArguments `
    -WorkingDirectory $projectRoot
$reportTrigger = New-ScheduledTaskTrigger `
    -Weekly `
    -WeeksInterval 1 `
    -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
    -At "15:25"
Register-ScheduledTask `
    -TaskName $reportTaskName `
    -Action $reportAction `
    -Trigger $reportTrigger `
    -Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10)) `
    -Principal $principal `
    -Description "Toss OpenAPI daily report fallback." `
    -Force | Out-Null

Get-ScheduledTask -TaskName $reportTaskName |
    Select-Object TaskName, State
Get-ScheduledTaskInfo -TaskName $reportTaskName |
    Select-Object NextRunTime, LastRunTime, LastTaskResult

$watchdogTaskName = "TossAutoTrading-Watchdog"
$watchdogScript = Join-Path $PSScriptRoot "watchdog.ps1"
$watchdogAction = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$watchdogScript`"" `
    -WorkingDirectory $projectRoot
$watchdogTrigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 1) `
    -RepetitionDuration (New-TimeSpan -Days 365)
Register-ScheduledTask `
    -TaskName $watchdogTaskName `
    -Action $watchdogAction `
    -Trigger $watchdogTrigger `
    -Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew) `
    -Principal $principal `
    -Description "Restarts the trading runner when its heartbeat stops." `
    -Force | Out-Null

Get-ScheduledTask -TaskName $watchdogTaskName |
    Select-Object TaskName, State

