@echo off
setlocal
pushd "%~dp0"

if exist venv rmdir /S /Q venv
python -m venv venv
call venv\Scripts\activate

python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

pyinstaller -F -w ui_testing\gui.py --name "UI Testing" ^
  --hidden-import ui_testing.action ^
  --hidden-import ui_testing.recorder ^
  --hidden-import ui_testing.player ^
  --hidden-import ui_testing.util ^
  --hidden-import pynput.keyboard ^
  --hidden-import pynput.mouse ^
  --hidden-import win32gui ^
  --hidden-import win32api ^
  --hidden-import win32con ^
  --hidden-import PIL.Image ^
  --hidden-import PIL.ImageTk ^
  --hidden-import PIL.ImageChops ^
  --hidden-import numpy ^
  --hidden-import openpyxl

set "EXE=dist\UI Testing.exe"
set "DESK=%USERPROFILE%\Desktop"
if exist "%EXE%" (
  copy /Y "%EXE%" "%DESK%\UI Testing.exe" >nul 2>&1
)

if not exist "%DESK%\UI Testing.exe" (
  for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set "REALDESK=%%D"
  if defined REALDESK (
    copy /Y "%EXE%" "%REALDESK%\UI Testing.exe" >nul 2>&1
  )
)

if exist "%DESK%\UI Testing.exe" (
  echo Deployed to "%DESK%\UI Testing.exe"
) else if defined REALDESK if exist "%REALDESK%\UI Testing.exe" (
  echo Deployed to "%REALDESK%\UI Testing.exe"
) else (
  echo Could not copy to Desktop. EXE is here: "%CD%\%EXE%"
)

popd
endlocal