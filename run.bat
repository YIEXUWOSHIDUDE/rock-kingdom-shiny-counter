@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import PySide6, cv2, mss, win32gui, torch, easyocr" >nul 2>&1
  if not errorlevel 1 goto run_venv
)
py -3.14 -m shiny_counter
goto finished

:run_venv
".venv\Scripts\python.exe" -m shiny_counter

:finished
if errorlevel 1 pause
