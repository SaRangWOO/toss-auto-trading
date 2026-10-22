$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$runtime = Join-Path $projectRoot 'research_data\paperclip'
$nodePath = (Get-Content (Join-Path $projectRoot 'state\paperclip-runtime.json') -Raw | ConvertFrom-Json).node
$gitDirectory = 'C:\Program Files\Git\cmd'
$env:PATH = (Join-Path $runtime 'native-runtime') + ';' + (Split-Path -Parent $nodePath) + ';' + $gitDirectory + ';' + $env:PATH
$env:PAPERCLIP_TELEMETRY_DISABLED = '1'
$env:DO_NOT_TRACK = '1'
# Do not inherit application-specific Node hooks from an interactive terminal.
Remove-Item Env:NODE_OPTIONS -ErrorAction SilentlyContinue
Remove-Item Env:NODE_PATH -ErrorAction SilentlyContinue
Set-Location $runtime
$ErrorActionPreference = 'Continue' # Windows PowerShell treats native stderr as ErrorRecord.
# On Windows the embedded Node launcher can fail after a restart. pg_ctl gives
# PostgreSQL a persistent log and waits for crash recovery before Node connects.
$pgCtl = Join-Path $runtime 'node_modules\.pnpm\@embedded-postgres+windows-x64@18.1.0-beta.16\node_modules\@embedded-postgres\windows-x64\native\bin\pg_ctl.exe'
$dbPath = Join-Path $runtime 'home\instances\default\db'
if (-not (Test-Path -LiteralPath $pgCtl) -or -not (Test-Path -LiteralPath (Join-Path $dbPath 'PG_VERSION'))) {
    throw 'Pinned PostgreSQL runtime or initialized database missing'
}
& $pgCtl -D $dbPath status *> $null
if ($LASTEXITCODE -ne 0) {
    $pgLog = Join-Path $projectRoot 'logs\paperclip-postgres.log'
    $pgArgs = "-D `"$dbPath`" -l `"$pgLog`" -t 60 -o `"-p 54329 -h 127.0.0.1`" start"
    # Avoid PowerShell's native pipeline waiting on PostgreSQL's inherited handles.
    $pgStart = Start-Process -FilePath $pgCtl -ArgumentList $pgArgs -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $projectRoot 'logs\paperclip-pg-start.log') -RedirectStandardError (Join-Path $projectRoot 'logs\paperclip-pg-start.err')
    if (-not $pgStart.WaitForExit(65000)) { exit 1 }
    if ($pgStart.ExitCode -ne 0) { exit 1 }
}
$entry = Join-Path $runtime 'node_modules\paperclipai\dist\index.js'
$dataHome = Join-Path $runtime 'home'
$nodeArgs = "`"$entry`" run --data-dir `"$dataHome`" --no-repair"
$server = Start-Process -FilePath $nodePath -ArgumentList $nodeArgs -WorkingDirectory $runtime -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $projectRoot 'logs\paperclip-current.log') -RedirectStandardError (Join-Path $projectRoot 'logs\paperclip-current.err')
$server.WaitForExit()
exit $server.ExitCode
