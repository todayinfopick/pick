@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 상품별 사진 폴더를 만듭니다...
".venv\Scripts\python.exe" make_folders.py
pause
