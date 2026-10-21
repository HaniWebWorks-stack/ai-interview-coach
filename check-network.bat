@echo off
REM Network check: can this laptop look up LiveKit's server addresses?
REM Compares your normal DNS with Google (8.8.8.8) and Cloudflare (1.1.1.1).
REM Read-only: changes nothing. Results go to logs\network-check.txt
cd /d "%~dp0"
if not exist logs mkdir logs
set OUT=logs\network-check.txt
set H1=interview-coach-lxsuzdrn.livekit.cloud
set H2=interview-coach-lxsuzdrn.ohyderabad1a.production.livekit.cloud
echo Network check %date% %time%> %OUT%
echo Checking (about 30 seconds)...
for %%H in (%H1% %H2%) do (
  for /L %%N in (1,1,3) do (
    echo. >> %OUT%
    echo ===== %%H  [your normal DNS, try %%N] >> %OUT%
    nslookup %%H >> %OUT% 2>&1
  )
  echo. >> %OUT%
  echo ===== %%H  [Google DNS 8.8.8.8] >> %OUT%
  nslookup %%H 8.8.8.8 >> %OUT% 2>&1
  echo. >> %OUT%
  echo ===== %%H  [Cloudflare DNS 1.1.1.1] >> %OUT%
  nslookup %%H 1.1.1.1 >> %OUT% 2>&1
)
echo. >> %OUT%
echo ===== Windows DNS settings >> %OUT%
powershell -NoProfile -Command "Get-DnsClientServerAddress -AddressFamily IPv4 | Where-Object {$_.ServerAddresses} | Format-Table InterfaceAlias,ServerAddresses -AutoSize | Out-String -Width 200" >> %OUT% 2>&1
echo.
echo Done. You can close this window.
echo You can close this window.
pause
