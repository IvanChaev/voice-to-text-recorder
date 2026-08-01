@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

set "PIDFILE=%~dp0logs\pid.pid"
set "LOGDIR=%~dp0logs"
set "LOGFILE=%~dp0logs\watchdog.log"
set "FLAGFILE=%~dp0logs\restart.flag"
set "INFOFILE=%~dp0logs\restart_info.flag"
set "STARTBAT=%~dp0start.bat"
set "IMAGENAME=pythonw.exe"
set "CHECK_INTERVAL=10"
set "CONFIRM_DEAD_COUNT=2"
set "RESTART_GRACE=15"
set "RESTART_WAIT=180"
set "BOOT_WAIT=180"
set "FLAG_MAX_AGE=300"
set "CRASH_LOOP_FAST=3"
set "COOLDOWN=120"
set "RESTART_ENABLED=1"

title Watchdog: my_voice_project

echo.
echo  ============================================
echo  Watchdog pid-файла: !PIDFILE!
echo  Интервал проверки: !CHECK_INTERVAL! сек
echo  Ожидание загрузки после перезапуска: !BOOT_WAIT! сек
echo  Флаг перезапуска: !FLAGFILE!
echo  Лог: !LOGFILE!
echo  ============================================
echo.

if not exist "!LOGDIR!" md "!LOGDIR!" 2>nul

set "ALIVE=0"
set "CAUSE="
set "LAST_STATUS="
set "DEAD_COUNT=0"
set "FAST_DEATHS=0"
set "MISSING_LOGGED=0"
set "PID="
set "FOUND="
set "ISNUM=0"
set "DUMMY=0"
set "FLAG="
set "FLAG_AGE=0"
set "MODE="
set "WAIT_ELAPSED=0"
set "START_REASON="

call :check_state
if "!ALIVE!"=="1" (
    set "START_REASON=restart"
    call :log "СТАТУС: программа работает (pid !PID!), начинаю наблюдение"
) else (
    set "START_REASON=first"
    call :log "СТАТУС: программа не запущена - !CAUSE!. Начинаю наблюдение"
)

:loop
call :check_state

if "!MODE!"=="wait_boot" (
    if "!ALIVE!"=="1" (
        set "MODE="
        set "DEAD_COUNT=0"
        set "FAST_DEATHS=0"
        set "LAST_STATUS=alive"
        if "!START_REASON!"=="first" (
            call :log "СТАТУС: программа запущена (pid !PID!), начинаю наблюдение"
        ) else (
            call :log "СТАТУС: программа запустилась после перезапуска (pid !PID!), начинаю наблюдение"
        )
    ) else (
        set /a "WAIT_ELAPSED+=!CHECK_INTERVAL!"
        if !WAIT_ELAPSED! GEQ !BOOT_WAIT! (
            set "MODE="
            set "DEAD_COUNT=0"
            if "!START_REASON!"=="first" (
                call :log "ОШИБКА: программа не поднялась за !BOOT_WAIT! сек после запуска - повторная попытка"
            ) else (
                call :log "ОШИБКА: программа не поднялась за !BOOT_WAIT! сек после перезапуска - повторная попытка"
            )
            call :try_restart
        )
    )
    call :sleep !CHECK_INTERVAL!
    goto :loop
)

if "!MODE!"=="wait_restart" (
    if "!ALIVE!"=="1" (
        set "MODE="
        set "DEAD_COUNT=0"
        set "FAST_DEATHS=0"
        set "LAST_STATUS=alive"
        call :log "СТАТУС: программа вернулась после внутреннего перезапуска (pid !PID!)"
    ) else (
        set /a "WAIT_ELAPSED+=!CHECK_INTERVAL!"
        if !WAIT_ELAPSED! GEQ !RESTART_WAIT! (
            set "MODE="
            set "DEAD_COUNT=0"
            set "LAST_STATUS="
            set "START_REASON=restart"
            call :log "ОШИБКА: внутренний перезапуск не удался, программа не вернулась за !RESTART_WAIT! сек - выполняю перезапуск"
            call :try_restart
        )
    )
    call :sleep !CHECK_INTERVAL!
    goto :loop
)

if "!ALIVE!"=="1" (
    set "DEAD_COUNT=0"
    set "FAST_DEATHS=0"
    if "!LAST_STATUS!"=="dead" call :log "СТАТУС: программа снова работает (pid !PID!)"
    set "LAST_STATUS=alive"
) else (
    set /a "DEAD_COUNT+=1"
    if !DEAD_COUNT! GEQ !CONFIRM_DEAD_COUNT! (
        call :read_flag
        if defined FLAG (
            if "!FLAG!"=="restart" (
                call :log "ИНФО: обнаружен внутренний перезапуск, ожидаю возвращения программы..."
                set "MODE=wait_restart"
                set "WAIT_ELAPSED=0"
                set "LAST_STATUS=dead"
                set "DEAD_COUNT=0"
            ) else (
                call :log "КРИТИЧНО: программа завершена нештатно - !CAUSE!"
                set "LAST_STATUS=dead"
                set "START_REASON=restart"
                if "!RESTART_ENABLED!"=="1" call :try_restart
            )
            if exist "!FLAGFILE!" del "!FLAGFILE!" 2>nul
        ) else (
            if "!LAST_STATUS!"=="alive" (
                set "START_REASON=restart"
                call :log "КРИТИЧНО: программа упала - !CAUSE!"
            ) else (
                set "START_REASON=first"
            )
            set "LAST_STATUS=dead"
            if "!RESTART_ENABLED!"=="1" call :try_restart
        )
    )
)
call :sleep !CHECK_INTERVAL!
goto :loop

:check_state
set "ALIVE=0"
set "CAUSE="
set "PID="
set "FOUND="
set "ISNUM=0"
if not exist "!PIDFILE!" (
    set "CAUSE=pid-файл отсутствует (!PIDFILE!)"
    exit /b 0
)
for /f "usebackq delims=" %%i in ("!PIDFILE!") do set "PID=%%i"
set "PID=!PID: =!"
if not defined PID (
    set "CAUSE=pid-файл пуст"
    exit /b 0
)
set /a "DUMMY=!PID!" 2>nul && set "ISNUM=1"
if not "!ISNUM!"=="1" (
    set "CAUSE=pid-файл содержит некорректное значение: !PID!"
    exit /b 0
)
for /f "tokens=2 delims=," %%a in ('tasklist /FI "PID eq !PID!" /FI "IMAGENAME eq !IMAGENAME!" /FO CSV /NH 2^>nul') do set "FOUND=%%a"
set "FOUND=!FOUND:"=!"
if "!FOUND!"=="!PID!" (
    set "ALIVE=1"
) else (
    set "CAUSE=процесс с pid !PID! (имя !IMAGENAME!) не найден"
)
exit /b 0

:read_flag
set "FLAG="
if not exist "!FLAGFILE!" exit /b 0
for /f "usebackq delims=" %%i in ("!FLAGFILE!") do set "FLAG=%%i"
set "FLAG=!FLAG: =!"
set "FLAG_AGE=0"
for /f "usebackq" %%a in (`powershell -NoProfile -Command "[int][math]::Floor(((Get-Date) - (Get-Item -LiteralPath '!FLAGFILE!').LastWriteTime).TotalSeconds)" 2^>nul`) do set "FLAG_AGE=%%a"
if !FLAG_AGE! GTR !FLAG_MAX_AGE! (
    call :log "ИНФО: флаг устарел (возраст !FLAG_AGE! сек, максимум !FLAG_MAX_AGE!) - падение считается реальным"
    set "FLAG="
    if exist "!FLAGFILE!" del "!FLAGFILE!" 2>nul
)
exit /b 0

:try_restart
set /a "FAST_DEATHS+=1"
if !FAST_DEATHS! GEQ !CRASH_LOOP_FAST! (
    call :log "ПРЕДУПРЕЖДЕНИЕ: программа падает слишком часто, пауза !COOLDOWN! сек"
    set "FAST_DEATHS=0"
    call :sleep !COOLDOWN!
)
if not exist "!STARTBAT!" (
    if not "!MISSING_LOGGED!"=="1" (
        call :log "ОШИБКА: не найден !STARTBAT!, перезапуск невозможен"
        set "MISSING_LOGGED=1"
    )
) else (
    if "!START_REASON!"=="restart" (
        echo watchdog> "!INFOFILE!"
    ) else (
        if exist "!INFOFILE!" del "!INFOFILE!" 2>nul
    )
    if "!START_REASON!"=="first" (
        call :log "ЗАПУСК программы..."
    ) else (
        call :log "ПЕРЕЗАПУСК программы..."
    )
    start "" /min "!STARTBAT!"
)
set "DEAD_COUNT=0"
set "LAST_STATUS="
set "MODE=wait_boot"
set "WAIT_ELAPSED=0"
call :sleep !RESTART_GRACE!
exit /b 0

:sleep
if %~1 gtr 0 (
    timeout /t %~1 /nobreak >nul 2>nul
    if errorlevel 1 ping -n %~1 -w 1000 127.0.0.1 >nul 2>nul
)
exit /b 0

:log
set "MSG=%~1"
echo [%date% %time%] !MSG!
cmd /u /c "echo [%date% %time%] !MSG! >>""!LOGFILE!"""
exit /b 0
