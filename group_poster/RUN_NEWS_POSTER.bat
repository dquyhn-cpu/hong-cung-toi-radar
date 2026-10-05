@echo off
echo [HCT] RUN_NEWS_POSTER da duoc hop nhat vao RUN_GROUP_POSTER.
call "%~dp0RUN_GROUP_POSTER.bat" %*
exit /b %ERRORLEVEL%
