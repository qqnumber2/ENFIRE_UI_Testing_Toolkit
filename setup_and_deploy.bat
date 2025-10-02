@echo off
setlocal
set "SCRIPT=%~dp0setup_and_deploy.ps1"
if not exist "%SCRIPT%" (
  echo Could not locate setup_and_deploy.ps1
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
endlocal

