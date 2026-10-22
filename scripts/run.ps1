param(
    [ValidateSet("check", "scan", "once", "run", "status", "report", "verify-live-order", "paper-lab-once", "paper-lab-run", "paper-lab-replay", "paper-lab-report")]
    [string]$Command = "status",
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Arguments
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Virtual environment not found. Run .\scripts\setup.cmd first."
}

$env:PYTHONPATH = Join-Path $projectRoot "src"
$pausePath = Join-Path $projectRoot "state\watchdog.pause"
# Lab is opt-in and must not silently resume the legacy scheduled runner.
if ($Command -notlike 'paper-lab-*') {
    Remove-Item -LiteralPath $pausePath -Force -ErrorAction SilentlyContinue
}
if ($Command -eq 'paper-lab-run') {
    $scheduled = Get-ScheduledTask -TaskName 'TossAutoTrading-Weekdays' -ErrorAction SilentlyContinue
    if ($scheduled -and ($scheduled.Actions.Arguments -join ' ') -match '\spaper-lab-run(?:\s|$)') {
        Remove-Item -LiteralPath $pausePath -Force -ErrorAction SilentlyContinue
    }
}
$logDir = Join-Path $projectRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$launcherLog = Join-Path $logDir "launcher.log"
$started = Get-Date -Format "yyyy-MM-dd HH:mm:ss K"
Add-Content -LiteralPath $launcherLog -Value "[$started] START command=$Command"
$previousErrorActionPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = "Continue"
    $instanceId = [Guid]::NewGuid().ToString("N")
    $stdoutPath = Join-Path $logDir "launcher.stdout.$instanceId.tmp"
    $stderrPath = Join-Path $logDir "launcher.stderr.$instanceId.tmp"
    & $python -m toss_trader.cli $Command --project-root $projectRoot @Arguments `
        1> $stdoutPath 2> $stderrPath
    $exitCode = $LASTEXITCODE
    foreach ($outputPath in @($stdoutPath, $stderrPath)) {
        if (Test-Path -LiteralPath $outputPath) {
            Get-Content -LiteralPath $outputPath | ForEach-Object {
                $_ | Out-File -LiteralPath $launcherLog -Append -Encoding utf8
                $_
            }
            Remove-Item -LiteralPath $outputPath -Force -ErrorAction SilentlyContinue
        }
    }
    $finished = Get-Date -Format "yyyy-MM-dd HH:mm:ss K"
    Add-Content -LiteralPath $launcherLog -Value "[$finished] EXIT command=$Command code=$exitCode"
    exit $exitCode
} catch {
    $failed = Get-Date -Format "yyyy-MM-dd HH:mm:ss K"
    Add-Content -LiteralPath $launcherLog -Value "[$failed] POWERSHELL_FATAL command=$Command error=$($_.Exception)"
    exit 1
} finally {
    $ErrorActionPreference = $previousErrorActionPreference
}
