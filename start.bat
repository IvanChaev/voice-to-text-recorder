@echo off
cd /d "%~dp0"
set "PYTHONW=pythonw.exe"
where pythonw.exe >nul 2>nul
if errorlevel 1 if exist "D:\programs\python3.11.8\pythonw.exe" set "PYTHONW=D:\programs\python3.11.8\pythonw.exe"
if not exist "%PYTHONW%" (
    echo [ERROR] pythonw.exe not found. Add Python to PATH or set a full path in start.bat.
    pause
    exit /b 1
)
start "" "%PYTHONW%" main.py
exit
