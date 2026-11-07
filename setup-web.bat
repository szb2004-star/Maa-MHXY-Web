@echo off
setlocal
cd /d "%~dp0"
set "MHXY_PYTHON=py -3.12"
%MHXY_PYTHON% -c "import sys" >nul 2>&1
if errorlevel 1 set "MHXY_PYTHON=py -3"
%MHXY_PYTHON% -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 (
  echo Install Python 3.10 or later with the Python Launcher first. Python 3.12 recommended.
  pause
  exit /b 1
)
%MHXY_PYTHON% -m venv .venv-web
if errorlevel 1 goto :failed
".venv-web\Scripts\python.exe" -m pip install -r requirements-web.txt
if errorlevel 1 goto :failed
echo Setup complete. Run start-web.bat and open http://127.0.0.1:8000
pause
exit /b 0
:failed
echo Setup failed. Review the error above and retry.
pause
exit /b 1
