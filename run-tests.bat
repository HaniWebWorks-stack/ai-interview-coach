@echo off
REM Runs the automated tests (no AI service or internet needed).
REM Results are written to logs\test-results.txt
cd /d "%~dp0"
if not exist logs mkdir logs
set VENV=%LOCALAPPDATA%\ai-interview-coach\venv
"%VENV%\Scripts\python.exe" -m unittest discover -s agent\tests -v > logs\test-results.txt 2>&1
type logs\test-results.txt
echo.
echo Done. You can close this window.
pause
