@echo off
rem Essay Reader launcher (Chinese filename alias).
rem ASCII-only on purpose: see start.cmd for why.
setlocal
cd /d "%~dp0"
chcp 65001 >nul 2>&1
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
set "EXITCODE=%ERRORLEVEL%"
if not "%EXITCODE%"=="0" (
  echo.
  echo [ERROR] Failed to start. Exit code: %EXITCODE%
  echo See the messages above. Common causes: missing dependencies
  echo ^(run scripts\setup.ps1 once^), or port 8787 already in use.
  echo.
  pause
)
endlocal