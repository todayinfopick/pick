@echo off
chcp 65001 >nul
cd /d "%~dp0"
for %%I in ("%~dp0.") do set "NAME=%%~nxI"
for /f "tokens=1 delims=," %%a in ('schtasks /Query /FO CSV /NH 2^>nul ^| findstr /i /c:"CoupangAutoPost_%NAME%_"') do schtasks /Delete /F /TN %%a >nul
echo [%NAME%] 자동 게시를 껐습니다. 수동 게시는 post_now.bat으로 계속 할 수 있습니다.
pause
