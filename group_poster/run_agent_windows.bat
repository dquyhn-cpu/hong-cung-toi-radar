@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
  exit /b 1
)

start "" /b ".venv\Scripts\pythonw.exe" group_agent.py
exit /b 0
