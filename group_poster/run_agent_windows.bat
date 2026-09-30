@echo off
setlocal
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$t=Get-ScheduledTask -TaskName 'HongCungToiGroupPosterAgent' -ErrorAction SilentlyContinue; if(-not $t){& '%~dp0install_agent_task.ps1'} else {Start-ScheduledTask -TaskName 'HongCungToiGroupPosterAgent'}"

exit /b %ERRORLEVEL%
