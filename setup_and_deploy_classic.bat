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

copy /Y dist\"UI Testing.exe" "%USERPROFILE%\Desktop\UI Testing.exe"

popd
endlocal