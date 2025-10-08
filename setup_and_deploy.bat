@echo off
setlocal
set PS1=%~dp0setup_and_deploy.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
if %ERRORLEVEL% NEQ 0 (
  echo.
  echo Setup failed with error %ERRORLEVEL%.
  pause
) else (
  echo.
  echo Setup succeeded.
  pause
)
