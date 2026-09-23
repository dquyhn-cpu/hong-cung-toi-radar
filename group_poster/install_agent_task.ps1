$ErrorActionPreference = "Stop"

$groupPoster = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonw = Join-Path $groupPoster ".venv\Scripts\pythonw.exe"
$agentPy = Join-Path $groupPoster "group_agent.py"

if (-not (Test-Path $pythonw)) {
  throw "pythonw.exe not found. Run setup_windows.bat first."
}

# Stop/remove any previous visible-console version.
try { Stop-ScheduledTask -TaskName "HongCungToiGroupPosterAgent" -ErrorAction SilentlyContinue } catch {}
try { Unregister-ScheduledTask -TaskName "HongCungToiGroupPosterAgent" -Confirm:$false -ErrorAction SilentlyContinue } catch {}

$action = New-ScheduledTaskAction -Execute $pythonw -Argument ("`"" + $agentPy + "`"") -WorkingDirectory $groupPoster
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName "HongCungToiGroupPosterAgent" -Action $action -Trigger $trigger -Settings $settings -Description "HCT Group Poster hidden queue agent" -Force | Out-Null
Start-ScheduledTask -TaskName "HongCungToiGroupPosterAgent"
Start-Sleep -Seconds 2
$task = Get-ScheduledTask -TaskName "HongCungToiGroupPosterAgent"
Write-Host ("Installed hidden task: " + $task.TaskName + " | State=" + $task.State)
Write-Host "No CMD window is required. Agent logs to group_poster\agent.log."
