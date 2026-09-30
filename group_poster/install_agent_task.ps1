$ErrorActionPreference = "Stop"

$groupPoster = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonw = Join-Path $groupPoster ".venv\Scripts\pythonw.exe"
$agentPy = Join-Path $groupPoster "group_agent.py"
$taskName = "HongCungToiGroupPosterAgent"

if (-not (Test-Path $pythonw)) {
  throw "pythonw.exe not found. Run setup_windows.bat first."
}
if (-not (Test-Path $agentPy)) {
  throw "group_agent.py not found."
}

# Kill only legacy/duplicate Group Poster agents. Do not touch the Facebook collector
# or the user's normal Chrome.
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match "group_agent\.py" } |
  ForEach-Object {
    try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {}
  }

try { Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue } catch {}
try { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue } catch {}

# IMPORTANT: pass normal Windows quotes, not backslash-escaped quotes.
$agentArgument = '"' + $agentPy + '"'
$action = New-ScheduledTaskAction -Execute $pythonw -Argument $agentArgument -WorkingDirectory $groupPoster
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -MultipleInstances IgnoreNew `
  -RestartCount 5 `
  -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description "HCT Group Poster canonical hidden queue agent" -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 3

$task = Get-ScheduledTask -TaskName $taskName
$info = Get-ScheduledTaskInfo -TaskName $taskName
Write-Host ("Installed canonical task: " + $task.TaskName + " | State=" + $task.State + " | LastTaskResult=" + $info.LastTaskResult)
Write-Host ("Action: " + $pythonw + " " + $agentArgument)
Write-Host "Only this task should start group_agent.py. Logs: group_poster\agent.log."
