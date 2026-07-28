param(
    [ValidateSet("check", "scan", "once", "run", "status")]
    [string]$Command = "status"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Virtual environment not found. Run .\scripts\setup.cmd first."
}

$env:PYTHONPATH = Join-Path $projectRoot "src"
& $python -m toss_trader.cli $Command --project-root $projectRoot
exit $LASTEXITCODE
