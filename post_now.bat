@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 지금 바로 다음 상품을 게시합니다...
".venv\Scripts\python.exe" main.py
pause
