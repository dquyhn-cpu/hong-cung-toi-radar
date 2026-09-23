$ErrorActionPreference = "Stop"
$groupPoster = Split-Path -Parent $MyInvocation.MyCommand.Path
$agentBat = Join-Path $groupPoster "run_agent_windows.bat"
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument ('/c "' + $agentBat + '"')
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "HongCungToiGroupPosterAgent" -Action $action -Trigger $trigger -Settings $settings -Description "HCT Group Poster queue agent" -Force
Write-Host "Installed scheduled task: HongCungToiGroupPosterAgent"
Write-Host "It will start automatically at Windows logon."
