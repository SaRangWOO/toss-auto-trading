$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$stateDir = Join-Path $projectRoot "state"
$logDir = Join-Path $projectRoot "logs"
$taskName = "TossAutoTrading-Weekdays"
$pausePath = Join-Path $stateDir "watchdog.pause"
$heartbeatPath = Join-Path $stateDir "live_heartbeat.json"
$watchdogLog = Join-Path $logDir "watchdog.log"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$now = Get-Date
$inWindow = $now.DayOfWeek -in @("Monday", "Tuesday", "Wednesday", "Thursday", "Friday") -and
    $now.TimeOfDay -ge ([TimeSpan]::Parse("09:04")) -and
    $now.TimeOfDay -lt ([TimeSpan]::Parse("15:20"))
if (-not $inWindow -or (Test-Path -LiteralPath $pausePath)) { exit 0 }

$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
$stale = $true
if (Test-Path -LiteralPath $heartbeatPath) {
    $age = $now - (Get-Item -LiteralPath $heartbeatPath).LastWriteTime
    $stale = $age.TotalSeconds -gt 120
}
if ($task -and ($task.State -ne "Running" -or $stale)) {
    $stamp = $now.ToString("yyyy-MM-dd HH:mm:ss K")
    Add-Content -LiteralPath $watchdogLog -Value "[$stamp] restart state=$($task.State) stale=$stale"
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Start-ScheduledTask -TaskName $taskName
}
