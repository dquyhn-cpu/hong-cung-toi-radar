@echo off
setlocal
cd /d "%~dp0.."
echo [HCT] Cap nhat code/job moi nhat...
git pull --rebase --autostash origin main
if errorlevel 1 (
  echo [HCT] Git pull loi. Van co the chay job dang co tren may.
)
echo.
echo [HCT] Chay News Poster LOCAL - khong qua GitHub queue.
echo [HCT] Co the keo file anh vao file RUN_NEWS_POSTER.bat de chay ngay.
echo.
py -3 "%~dp0local_news_runner.py" %*
set RC=%ERRORLEVEL%
echo.
if "%RC%"=="0" (
  echo [HCT] Hoan tat. Xem report: group_poster\output\group_batch_report.json
) else (
  echo [HCT] Dung voi ma loi %RC%. Xem cua so Chromium va report/log.
)
pause
exit /b %RC%
