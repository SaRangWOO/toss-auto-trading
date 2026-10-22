param([ValidateSet('run', 'paper-lab-run')][string]$Runner = 'run', [datetime]$StartDate = [datetime]::Today)
$ErrorActionPreference = "Stop"

$taskName = "TossAutoTrading-Weekdays"
$projectRoot = Split-Path -Parent $PSScriptRoot
$runScript = Join-Path $PSScriptRoot "run.ps1"
$arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$runScript`" $Runner"

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument $arguments `
    -WorkingDirectory $projectRoot

$trigger = New-ScheduledTaskTrigger `
    -Weekly `
    -WeeksInterval 1 `
    -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
    -At "09:00"
$trigger.StartBoundary = $StartDate.Date.AddHours(9).ToString('yyyy-MM-ddTHH:mm:ss')

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
$reportCommand = if ($Runner -eq 'paper-lab-run') { 'paper-lab-report' } else { 'report' }
$reportArguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$runScript`" $reportCommand"
$reportAction = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument $reportArguments `
    -WorkingDirectory $projectRoot
$processStopTime = [TimeSpan]::Parse("15:40")
$envPath = Join-Path $projectRoot ".env"
if (Test-Path -LiteralPath $envPath) {
    $processStopLine = Get-Content -LiteralPath $envPath |
        Where-Object { $_ -match '^\s*PROCESS_STOP_TIME\s*=\s*([0-2]\d:[0-5]\d)\s*(?:#.*)?$' } |
        Select-Object -First 1
    if ($processStopLine -and $processStopLine -match '^\s*PROCESS_STOP_TIME\s*=\s*([0-2]\d:[0-5]\d)') {
        $processStopTime = [TimeSpan]::Parse($Matches[1])
    }
}
$reportAt = ([DateTime]::Today.Add($processStopTime)).AddMinutes(2).ToString("HH:mm")
if ($Runner -eq 'paper-lab-run') {
    $labPolicy = Get-Content -LiteralPath (Join-Path $projectRoot 'config/paper_lab_v3.json') -Raw | ConvertFrom-Json
    $reportAt = ([DateTime]::Today.Add([TimeSpan]::Parse($labPolicy.stop_time))).AddMinutes(2).ToString('HH:mm')
}
$reportTrigger = New-ScheduledTaskTrigger `
    -Weekly `
    -WeeksInterval 1 `
    -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
    -At $reportAt
$reportTrigger.StartBoundary = $StartDate.Date.Add([TimeSpan]::Parse($reportAt)).ToString('yyyy-MM-ddTHH:mm:ss')
Register-ScheduledTask `
    -TaskName $reportTaskName `
    -Action $reportAction `
    -Trigger $reportTrigger `
    -Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10)) `
    -Principal $principal `
    -Description "Toss OpenAPI daily report fallback after PROCESS_STOP_TIME." `
    -Force | Out-Null

Get-ScheduledTask -TaskName $reportTaskName |
    Select-Object TaskName, State
Get-ScheduledTaskInfo -TaskName $reportTaskName |
    Select-Object NextRunTime, LastRunTime, LastTaskResult

$watchdogTaskName = "TossAutoTrading-Watchdog"
$watchdogScript = Join-Path $PSScriptRoot "watchdog.ps1"
$watchdogAction = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$watchdogScript`"" `
    -WorkingDirectory $projectRoot
$watchdogTrigger = New-ScheduledTaskTrigger `
    -Once `
    -At ($StartDate.Date.AddHours(9)) `
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

