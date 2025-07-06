@echo off
REM ============================================================================
REM =          Automated Trading Bot Launcher & Keeper (run_bot.bat)           =
REM ============================================================================
REM This script ensures the MT5 terminal is running before launching the Python
REM bot keeper. It will automatically restart the entire process if the keeper
REM script ever stops. This provides a robust, multi-layered approach to
REM achieving 24/7 uptime.
REM
REM Layers of Protection:
REM 1. This BAT file: Manages the MT5 terminal and the Python keeper process.
REM 2. script_keeper.py: Manages the main trading script (main.py).
REM 3. main.py: Manages connections to Telegram and MT5.

:: ========================= CONFIGURATION =========================
:: IMPORTANT: Set this to the full path of your MT5 terminal executable.
:: Use quotes to handle spaces in the path.
set "MT5_EXE_PATH=C:\Program Files\XM Global MT5\terminal64.exe"

:: The name of the MT5 process (usually terminal64.exe or terminal.exe)
set "MT5_PROCESS_NAME=terminal64.exe"

:: The command to run your Python script keeper.
set "PYTHON_KEEPER_COMMAND=python script_keeper.py main.py"

:: Delay in seconds to wait for MT5 to start up before launching the bot.
set "STARTUP_DELAY_SECONDS=30"

:: Delay in seconds before restarting the main loop if the keeper exits.
set "LOOP_DELAY_SECONDS=10"
:: =================================================================

:MAIN_LOOP
    cls
    echo ============================================================
    echo           Trading Bot System Initializing
    echo ============================================================
    echo.
    echo [%time%] Checking for MetaTrader 5 terminal...

    REM Check if the MT5 process is already running
    tasklist /FI "IMAGENAME eq %MT5_PROCESS_NAME%" 2>NUL | find /I /N "%MT5_PROCESS_NAME%">NUL
    
    REM The %ERRORLEVEL% variable will be 0 if the process was found, 1 if not.
    if "%ERRORLEVEL%"=="1" (
        echo [%time%] MT5 terminal is not running.
        echo [%time%] Starting MT5 from: %MT5_EXE_PATH%
        start "" "%MT5_EXE_PATH%"
        echo [%time%] Waiting %STARTUP_DELAY_SECONDS% seconds for the terminal to load...
        timeout /t %STARTUP_DELAY_SECONDS% /nobreak > NUL
    ) else (
        echo [%time%] MT5 terminal is already running. Proceeding.
    )

    echo.
    echo ============================================================
    echo           Launching Python Script Keeper
    echo ============================================================
    echo [%time%] Starting command: %PYTHON_KEEPER_COMMAND%
    echo.

    REM Start the Python script keeper. This will block here until the keeper exits.
    %PYTHON_KEEPER_COMMAND%

    echo.
    echo ============================================================
    echo           !!! WARNING: Keeper Process Exited !!!
    echo ============================================================
    echo [%time%] The Python keeper script has stopped.
    echo [%time%] The entire system will restart in %LOOP_DELAY_SECONDS% seconds.
    echo [%time%] Press Ctrl+C to abort the restart.
    
    timeout /t %LOOP_DELAY_SECONDS% /nobreak
    
    REM Loop back to the beginning to restart the whole process
    goto MAIN_LOOP