$ErrorActionPreference = "Stop"

$taskName = "TossAutoTrading-Weekdays"
$projectRoot = Split-Path -Parent $PSScriptRoot
$normalizedRoot = [IO.Path]::GetFullPath($projectRoot).TrimEnd('\')

Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
Stop-ScheduledTask -TaskName TossAutoTrading-DailyReport -ErrorAction SilentlyContinue
$pausePath = Join-Path $projectRoot "state\watchdog.pause"
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $pausePath) | Out-Null
Set-Content -LiteralPath $pausePath -Value "paused" -Encoding ascii

$targets = Get-CimInstance Win32_Process |
    Where-Object {
        $_.Name -eq "python.exe" -and
        $_.CommandLine -like "*toss_trader.cli run*" -and
        $_.CommandLine -like "*$normalizedRoot*"
    } |
    Sort-Object CreationDate -Descending

foreach ($target in $targets) {
    Stop-Process -Id $target.ProcessId -Force -ErrorAction SilentlyContinue
}

Start-Sleep -Seconds 1
$remaining = Get-CimInstance Win32_Process |
    Where-Object {
        $_.Name -eq "python.exe" -and
        $_.CommandLine -like "*toss_trader.cli run*" -and
        $_.CommandLine -like "*$normalizedRoot*"
    }

if ($remaining) {
    throw "Trading processes are still running: $($remaining.ProcessId -join ', ')"
}

Write-Output "Toss auto trading stopped safely."
