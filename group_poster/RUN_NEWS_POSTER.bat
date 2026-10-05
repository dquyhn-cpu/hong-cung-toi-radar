@echo off
setlocal
echo [HCT] RUN_NEWS_POSTER la wrapper cua Group Poster chung.
echo [HCT] Dang dung job: group_poster\local_jobs\current_group_job.json
call "%~dp0RUN_GROUP_POSTER.bat" %*
exit /b %ERRORLEVEL%
