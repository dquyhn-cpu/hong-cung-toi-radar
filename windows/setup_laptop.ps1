param(
  [string]$RepoUrl = "https://github.com/dquyhn-cpu/hong-cung-toi-radar.git",
  [string]$InstallDir = "$env:USERPROFILE\hong-cung-toi-radar"
)

$ErrorActionPreference = "Stop"

function Ensure-Command($Name, $WingetId) {
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
      throw "$Name is missing and winget is unavailable. Install $Name manually, then rerun this script."
    }
    winget install --id $WingetId --exact --accept-package-agreements --accept-source-agreements
  }
}

Ensure-Command "git" "Git.Git"
Ensure-Command "python" "Python.Python.3.12"

if (-not (Test-Path $InstallDir)) {
  git clone $RepoUrl $InstallDir
}

Set-Location $InstallDir
git fetch origin
git pull --rebase --autostash origin main

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium

$pythonExe = (Get-Command python).Source
$groupAgent = Join-Path $InstallDir "group_poster\group_agent.py"
$fbAgent = Join-Path $InstallDir "facebook_collector_agent.py"

$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

$groupAction = New-ScheduledTaskAction -Execute $pythonExe -Argument ('"' + $groupAgent + '"')
Register-ScheduledTask -TaskName "HongCungToiGroupPosterAgent" -Action $groupAction -Trigger $trigger -Settings $settings -Force | Out-Null

$fbAction = New-ScheduledTaskAction -Execute $pythonExe -Argument ('"' + $fbAgent + '"')
Register-ScheduledTask -TaskName "HongCungToiFacebookCollector" -Action $fbAction -Trigger $trigger -Settings $settings -Force | Out-Null

Write-Host ""
Write-Host "INSTALL_OK"
Write-Host "Next steps:"
Write-Host "1) Authenticate Git once if prompted: git pull origin main"
Write-Host "2) Radar Facebook login: python facebook_collector_local.py --login"
Write-Host "3) Group Poster login: python group_poster\group_poster.py --login"
Write-Host "4) Start collector: Start-ScheduledTask -TaskName HongCungToiFacebookCollector"
Write-Host "5) Start poster: Start-ScheduledTask -TaskName HongCungToiGroupPosterAgent"
