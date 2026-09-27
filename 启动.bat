@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在启动竹喧 …
".venv\Scripts\python.exe" app.py
echo.
echo 竹喧已退出。如果上面有报错信息，把它发给我。
pause
