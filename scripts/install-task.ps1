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

