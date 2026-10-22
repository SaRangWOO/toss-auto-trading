$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$runtime = Join-Path $projectRoot 'research_data\vibe-trading'
$upstream = Join-Path $runtime 'upstream'
$pin = Get-Content (Join-Path $PSScriptRoot 'upstream.json') -Raw | ConvertFrom-Json
if (-not (Test-Path $upstream)) {
    git clone --no-checkout $pin.repository $upstream
    if ($LASTEXITCODE -ne 0) { throw 'Clone failed' }
    git -C $upstream checkout --detach $pin.commit
    if ($LASTEXITCODE -ne 0) { throw 'Pinned checkout failed' }
}
$revision = git -C $upstream rev-parse HEAD
if ($revision -ne $pin.commit -or (git -C $upstream status --porcelain)) {
    throw 'Upstream pin mismatch or local edits; keep existing checkout for review'
}
$python = Join-Path $runtime 'venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    & (Join-Path $projectRoot '.venv\Scripts\python.exe') -m venv (Join-Path $runtime 'venv')
    if ($LASTEXITCODE -ne 0) { throw 'Research venv creation failed' }
}
& $python -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Research dependencies failed' }
Write-Output 'Offline Vibe-Trading journal environment ready.'
