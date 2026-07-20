@echo off
cd /d "%~dp0"
if not exist logs mkdir logs
python main.py 2>> logs\native_crash.log
pause
