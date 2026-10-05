@echo off
setlocal
echo [HCT] RUN_NEWS_POSTER - tu dong dung dung ten file anh duoc keo-tha vao BAT.
echo [HCT] Khong can doi ten anh. JPG/JPEG/PNG/WEBP deu duoc chap nhan.
echo [HCT] Dang dung job: group_poster\local_jobs\current_group_job.json
echo.
call "%~dp0RUN_GROUP_POSTER.bat" %*
exit /b %ERRORLEVEL%
