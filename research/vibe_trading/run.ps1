param(
    [Parameter(Mandatory=$true)][string]$Through,
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [switch]$RefreshSymbols
)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$bridge = Join-Path $PSScriptRoot 'bridge.py'
$researchPython = Join-Path $projectRoot 'research_data\vibe-trading\venv\Scripts\python.exe'
if (-not (Test-Path $researchPython)) { throw 'Run research\vibe_trading\setup.ps1 first' }
$exportArgs = @($bridge, 'export', '--through', $Through, '--output', $OutputDirectory)
if ($RefreshSymbols) { $exportArgs += '--refresh-symbols' }
& (Join-Path $projectRoot '.venv\Scripts\python.exe') @exportArgs
if ($LASTEXITCODE -ne 0) { throw 'Research export failed' }
& $researchPython $bridge analyze $OutputDirectory
if ($LASTEXITCODE -ne 0) { throw 'Vibe journal analysis/reconciliation failed' }
Write-Output "Report: $OutputDirectory\REPORT.md"
