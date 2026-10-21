@echo off
REM AI Interview Coach - environment check.
REM Only READS version numbers and writes them to environment-report.txt.
REM It does not install, change or delete anything.
cd /d "%~dp0"
set OUT=environment-report.txt
echo AI Interview Coach - environment report> "%OUT%"
echo Created: %date% %time%>> "%OUT%"
echo.>> "%OUT%"

echo === Windows ===>> "%OUT%"
powershell -NoProfile -Command "$o=Get-CimInstance Win32_OperatingSystem; $c=Get-CimInstance Win32_ComputerSystem; $d=Get-PSDrive C; 'OS: ' + $o.Caption + ' ' + $o.Version; 'RAM (GB): ' + [math]::Round($c.TotalPhysicalMemory/1GB,1); 'Free disk C: (GB): ' + [math]::Round($d.Free/1GB,1)" >> "%OUT%" 2>&1
echo.>> "%OUT%"

echo === python ===>> "%OUT%"
where python >> "%OUT%" 2>&1
python --version >> "%OUT%" 2>&1
echo === py launcher ===>> "%OUT%"
py --version >> "%OUT%" 2>&1
py -0p >> "%OUT%" 2>&1
echo === node ===>> "%OUT%"
node --version >> "%OUT%" 2>&1
echo === npm ===>> "%OUT%"
call npm --version >> "%OUT%" 2>&1
echo === git ===>> "%OUT%"
git --version >> "%OUT%" 2>&1
echo === uv ===>> "%OUT%"
uv --version >> "%OUT%" 2>&1
echo === VS Code ===>> "%OUT%"
call code --version >> "%OUT%" 2>&1
echo.>> "%OUT%"
echo END OF REPORT>> "%OUT%"

echo.
echo Done. You can close this window.
echo You can close this window.
pause
