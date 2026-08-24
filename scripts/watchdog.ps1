$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$stateDir = Join-Path $projectRoot "state"
$logDir = Join-Path $projectRoot "logs"
$taskName = "TossAutoTrading-Weekdays"
$pausePath = Join-Path $stateDir "watchdog.pause"
$watchdogLog = Join-Path $logDir "watchdog.log"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$mode = "paper"
$processStopTime = [TimeSpan]::Parse("15:40")
$envPath = Join-Path $projectRoot ".env"
if (Test-Path -LiteralPath $envPath) {
    foreach ($line in Get-Content -LiteralPath $envPath) {
        if ($line -match '^\s*TRADING_MODE\s*=\s*(paper|live)\s*(?:#.*)?$') {
            $mode = $Matches[1].ToLowerInvariant()
        }
        if ($line -match '^\s*PROCESS_STOP_TIME\s*=\s*([0-2]\d:[0-5]\d)\s*(?:#.*)?$') {
            $processStopTime = [TimeSpan]::Parse($Matches[1])
        }
    }
}
$heartbeatPath = Join-Path $stateDir "${mode}_heartbeat.json"
$normalizedRoot = [IO.Path]::GetFullPath($projectRoot).TrimEnd('\')
$now = Get-Date
$inWindow = $now.DayOfWeek -in @("Monday", "Tuesday", "Wednesday", "Thursday", "Friday") -and
    $now.TimeOfDay -ge ([TimeSpan]::Parse("09:04")) -and
    $now.TimeOfDay -lt $processStopTime
if (-not $inWindow -or (Test-Path -LiteralPath $pausePath)) { exit 0 }

$runnerProcesses = Get-CimInstance Win32_Process |
    Where-Object {
        $_.Name -eq "python.exe" -and
        $_.CommandLine -like "*toss_trader.cli run*" -and
        $_.CommandLine -like "*$normalizedRoot*"
    }
$processRunning = @($runnerProcesses).Count -gt 0
$stale = $true
if (Test-Path -LiteralPath $heartbeatPath) {
    $age = $now - (Get-Item -LiteralPath $heartbeatPath).LastWriteTime
    $stale = $age.TotalSeconds -gt 120
}
if (-not $processRunning -or $stale) {
    $stamp = $now.ToString("yyyy-MM-dd HH:mm:ss K")
    Add-Content -LiteralPath $watchdogLog -Value "[$stamp] restart mode=$mode process=$processRunning stale=$stale"
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($stale) {
        foreach ($process in $runnerProcesses) {
            Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
        }
    }
    Start-ScheduledTask -TaskName $taskName
}
