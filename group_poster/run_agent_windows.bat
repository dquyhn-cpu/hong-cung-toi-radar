@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Virtual environment not found.
  echo Run setup_windows.bat first.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" group_agent.py
