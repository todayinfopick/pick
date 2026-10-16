@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0auto_on.ps1"
if errorlevel 1 echo.& echo 예약 등록에 실패했습니다. 이 창을 캡처해서 보여 주세요.
pause
