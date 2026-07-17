@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m shiny_counter
) else (
  py -3.14 -m shiny_counter
)
if errorlevel 1 pause
