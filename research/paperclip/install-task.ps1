$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$PSScriptRoot\server.ps1`"" -WorkingDirectory $projectRoot
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$trigger = New-ScheduledTaskTrigger -Daily -At '08:45'
$trigger.StartBoundary = ([datetime]'2026-10-22T08:45:00').ToString('yyyy-MM-ddTHH:mm:ss')
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit ([timespan]::Zero) -MultipleInstances IgnoreNew -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'TossResearch-Paperclip' -Action $action -Trigger @($trigger, (New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME")) -Settings $settings -Principal $principal -Description 'Local Paperclip control plane; deterministic read-only research workers.' -Force | Out-Null
Get-ScheduledTask -TaskName 'TossResearch-Paperclip' | Select-Object TaskName,State
