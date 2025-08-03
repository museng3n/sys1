@echo off
echo 🛡️ SECURE TRADING SYSTEM STARTING
echo ======================================

echo [%time%] Checking security files...
if not exist "config.json.encrypted" (
    echo ❌ Encrypted config missing!
    pause
    exit
)

if not exist "secret.key" (
    echo ❌ Security key missing!
    pause
    exit
)

echo [%time%] Starting malware protection...
start /min python malware_protection.py

echo [%time%] Starting MT5...
start "" "C:\Program Files\XM Global MT5\terminal64.exe"

timeout /t 10

echo [%time%] Starting secure trading system...
python main.py

pause