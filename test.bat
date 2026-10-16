@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ===== 계정 연결 점검 =====
".venv\Scripts\python.exe" connect.py
echo.
echo ===== 글/이미지 미리보기 (실제로 게시되지 않음) =====
".venv\Scripts\python.exe" main.py --dry-run
pause
