@echo off
cd /d "%~dp0"
:: Запуск через консольный python.exe с перенаправлением stderr в файл
python main.py 2>> native_crash.log
pause