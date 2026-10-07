@echo off
setlocal
cd /d "%~dp0.."
echo [HCT] Cap nhat code/job moi nhat...
git pull --rebase --autostash origin main
if errorlevel 1 echo [HCT] Git pull loi. Van co the chay job dang co tren may.
echo.
echo [HCT] GROUP POSTER LOCAL - dung chung cho moi mang.
echo [HCT] Keo anh vao RUN_GROUP_POSTER.bat de chay job hien tai.
echo.
py -3 "%~dp0local_group_runner.py" %*
set RC=%ERRORLEVEL%
echo.
echo [HCT] Dong bo cac nhom NOT_MEMBER vao HOLD tap trung...
py -3 "%~dp0sync_dynamic_hold.py"
if errorlevel 1 echo [HCT] Canh bao: chua day duoc HOLD tap trung len GitHub.
echo.
if "%RC%"=="0" (
  echo [HCT] Hoan tat. Xem report: group_poster\output\group_batch_report.json
) else (
  echo [HCT] Dung voi ma loi %RC%. Xem Chromium va report/log.
)
pause
exit /b %RC%
