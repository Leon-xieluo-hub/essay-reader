@echo off
rem Essay Reader launcher.
rem Keep this file ASCII-only: cmd.exe decodes .cmd files with the active ANSI
rem code page, so non-ASCII bytes here would be mis-decoded into stray commands
rem and the window would flash and close. Chinese text lives in start.ps1, which
rem is saved as UTF-8 with BOM and therefore decodes correctly.
setlocal
cd /d "%~dp0"
rem Python logs UTF-8; switch the console to UTF-8 (65001) so Chinese messages
rem are readable instead of mojibake under the default 936 code page.
chcp 65001 >nul 2>&1
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
echo Starting Essay Reader, please wait...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
set "EXITCODE=%ERRORLEVEL%"
echo.
if not "%EXITCODE%"=="0" (
  echo [ERROR] Essay Reader failed to start. Exit code: %EXITCODE%
  echo Read the messages above; a common cause is a missing Python dependency
  echo ^(run scripts\setup.ps1 once^) or a port conflict on 8787.
  echo.
  pause
)
endlocal
