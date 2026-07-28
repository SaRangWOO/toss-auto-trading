$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $venvPython)) {
    $python = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($python) {
        & $python.Source -3 -m venv (Join-Path $projectRoot ".venv")
    }
    else {
        $python = Get-Command python.exe -ErrorAction SilentlyContinue
        if (-not $python -or $python.Source -like "*WindowsApps*") {
            $python = Get-ChildItem `
                -Path "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" `
                -File `
                -ErrorAction SilentlyContinue |
                Sort-Object FullName -Descending |
                Select-Object -First 1
        }
        if (-not $python) {
            throw "Python 3.11+ is required. Run: winget install --id Python.Python.3.13 -e --source winget"
        }
        $pythonPath = if ($python.Source) { $python.Source } else { $python.FullName }
        & $pythonPath -m venv (Join-Path $projectRoot ".venv")
    }
}

& $venvPython --version
Write-Host ""
Write-Host "Setup complete. Add TOSS_CLIENT_SECRET to .env, then run:"
Write-Host "  .\scripts\run.cmd check"
Write-Host "  .\scripts\run.cmd scan"
Write-Host "  .\scripts\run.cmd run"
