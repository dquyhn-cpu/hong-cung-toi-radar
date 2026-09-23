@echo off
setlocal
cd /d "%~dp0"
if not exist .venv (
  python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -r requirements.txt
python -m playwright install chromium
echo.
echo Setup complete.
echo Run: python group_poster.py --login
pause
