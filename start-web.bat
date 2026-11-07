@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv-web\Scripts\python.exe" (
  echo Please run setup-web.bat first.
  pause
  exit /b 1
)
".venv-web\Scripts\python.exe" -m web %*
if errorlevel 1 pause
