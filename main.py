# Enhanced main.py with Network Monitoring - Complete System
import json
import logging
import asyncio
import os
import sys
import time
import socket
import subprocess
import platform
from datetime import datetime, timedelta
from telethon import TelegramClient, events
from signal_parser import parse_signal
from mt5_handler import MT5Handler
from partial_closing_manager import PartialClosingManager

# Import security modules
from secure_config import load_secure_config
from security_monitoring import SecurityMonitor

# Setup Logging
LOGS_DIR = 'logs'
if not os.path.exists(LOGS_DIR):
    os.makedirs(LOGS_DIR)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(module)s:%(lineno)d] - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOGS_DIR, "enhanced_trading_system.log")),
        logging.FileHandler(os.path.join(LOGS_DIR, "security.log")),
        logging.StreamHandler(sys.stdout)
    ]
)
logging.getLogger('telethon').setLevel(logging.WARNING)

class NetworkMonitor:
    """Simple network monitoring for trading system"""
    
    def __init__(self):
        self.connection_drops = 0
        self.last_stability_report = time.time()
    
    def test_connection(self, timeout=5):
        """Test internet connectivity"""
        test_servers = [
            ("8.8.8.8", 53),           # Google DNS
            ("1.1.1.1", 53),           # Cloudflare DNS
            ("api.telegram.org", 443)  # Telegram API
        ]
        
        successful = 0
        for host, port in test_servers:
            try:
                sock = socket.create_connection((host, port), timeout)
                sock.close()
                successful += 1
            except (socket.error, socket.timeout):
                continue
        
        is_stable = successful >= 2  # At least 2/3 must work
        
        if not is_stable:
            self.connection_drops += 1
            logging.warning(f" Network unstable! ({successful}/{len(test_servers)} tests passed)")
        
        # Report stability every hour
        if time.time() - self.last_stability_report > 3600:
            logging.info(f" Network drops in last period: {self.connection_drops}")
            self.connection_drops = 0  # Reset counter
            self.last_stability_report = time.time()
        
        return is_stable

async def main():
    """Enhanced main function with network monitoring"""
    
    # Initialize network monitor
    network_monitor = NetworkMonitor()
    
    # Initialize security monitor
    security_monitor = SecurityMonitor()
    security_monitor.log_connection_event("SYSTEM_START", "Enhanced secure trading system starting")
    
    try:
        # Load config securely
        config = load_secure_config()
        if not config:
            security_monitor.log_connection_event("CONFIG_LOAD_FAILED", "Failed to load secure configuration")
            return
        
        security_monitor.log_connection_event("CONFIG_LOADED", "Configuration loaded successfully")
        logging.info("Secure configuration loaded successfully.")
        
    except Exception as e:
        security_monitor.log_connection_event("CONFIG_ERROR", f"Critical error: {e}")
        logging.critical(f" Critical error loading secure config: {e}. System cannot start.")
        return

    # Initialize MT5 and Position Manager
    mt5_handlers = []
    position_manager = PartialClosingManager([], config['trading_settings'])
    
    for account_config in config.get('accounts', []):
        try:
            handler = MT5Handler(account_config, config['trading_settings'], position_manager)
            mt5_handlers.append(handler)
            security_monitor.log_connection_event("MT5_CONNECTED", f"Account: {account_config.get('login')}")
        except ConnectionError as e:
            security_monitor.log_connection_event("MT5_CONNECTION_FAILED", f"Account: {account_config.get('login')}, Error: {e}")
            logging.error(f"Could not start handler for account {account_config.get('login', 'N/A')}: {e}")
    
    if not mt5_handlers:
        security_monitor.log_connection_event("NO_MT5_HANDLERS", "No MT5 accounts connected")
        logging.critical(" No MT5 accounts connected. System cannot start.")
        return

    position_manager.handlers = mt5_handlers
    position_manager.start()

    # Telegram client setup
    telegram_config = config['telegram']
    client = TelegramClient(
        telegram_config['session_name'],
        telegram_config['api_id'],
        telegram_config['api_hash']
    )

    @client.on(events.NewMessage(chats=telegram_config['target_channel_ids']))
    async def new_message_handler(event):
        security_monitor.log_connection_event("MESSAGE_RECEIVED", f"Channel: {event.chat_id}")
        logging.info(f"--- New Message Received from Channel {event.chat_id} ---")
        
        message_text = event.message.message
        
        if parsed_signal := parse_signal(message_text):
            security_monitor.log_connection_event("SIGNAL_PARSED", f"Symbol: {parsed_signal['symbol']}")
            logging.info(f"Signal parsed for {parsed_signal['symbol']}. Distributing to all active MT5 handlers.")
            tasks = [asyncio.to_thread(handler.execute_trade, parsed_signal) for handler in mt5_handlers]
            await asyncio.gather(*tasks, return_exceptions=True)
        else:
            logging.warning("Message did not contain a valid/parsable signal.")

    # Enhanced monitoring task
    async def enhanced_monitoring_loop():
        while True:
            await asyncio.sleep(300)  # Check every 5 minutes
            security_monitor.check_file_integrity()
            security_monitor.check_unauthorized_access()
            
            # Network stability check
            if not network_monitor.test_connection():
                logging.warning(" Network instability detected during monitoring")

    try:
        # Enhanced connection loop with intelligent reconnection
        max_consecutive_failures = 5
        consecutive_failures = 0
        base_delay = 30
        
        while True:
            try:
                # Test network before connection attempt
                if not network_monitor.test_connection():
                    logging.warning("Network unstable, waiting before Telegram connection...")
                    await asyncio.sleep(60)
                    continue
                
                security_monitor.log_connection_event("TELEGRAM_CONNECTING", "Attempting Telegram connection")
                logging.info("Attempting to connect to Telegram...")
                
                await client.start()
                
                security_monitor.log_connection_event("TELEGRAM_CONNECTED", "Successfully connected to Telegram")
                logging.info(" Telegram client connected successfully. Listening for signals...")
                
                # Reset failure counter on successful connection
                consecutive_failures = 0
                
                # Start enhanced monitoring
                asyncio.create_task(enhanced_monitoring_loop())
                
                await client.run_until_disconnected()
            
            except (ConnectionError, TimeoutError, OSError) as e:
                consecutive_failures += 1
                security_monitor.log_connection_event("CONNECTION_ERROR", f"Connection lost: {e}")
                logging.warning(f" Telegram connection lost: {e}")
                
                # Test network stability
                if network_monitor.test_connection():
                    logging.info(" Network is stable, quick reconnect...")
                    delay = base_delay
                else:
                    logging.error(" Network appears unstable, longer wait...")
                    delay = base_delay * 3
                
                # Increase delay if multiple consecutive failures
                if consecutive_failures > 3:
                    delay = delay * consecutive_failures
                    logging.warning(f" Multiple failures ({consecutive_failures}), waiting {delay} seconds...")
                
                # Cap maximum delay at 5 minutes
                delay = min(delay, 300)
                
                logging.info(f" Reconnecting in {delay} seconds...")
                await asyncio.sleep(delay)
                
                # Reset if too many consecutive failures
                if consecutive_failures >= max_consecutive_failures:
                    logging.error(f" Too many consecutive failures ({consecutive_failures}), resetting...")
                    consecutive_failures = 0
                    await asyncio.sleep(300)  # Wait 5 minutes before reset
            
            except Exception as e:
                security_monitor.log_connection_event("SYSTEM_ERROR", f"Critical error: {e}")
                logging.critical(f" Unexpected critical error: {e}", exc_info=True)
                
                if client.is_connected():
                    await client.disconnect()
                
                logging.info(" Attempting recovery in 120 seconds...")
                await asyncio.sleep(120)
    
    except (KeyboardInterrupt, SystemExit):
        security_monitor.log_connection_event("USER_INTERRUPT", "System interruption detected")
        logging.info(" System interruption detected (e.g., Ctrl+C).")
    
    finally:
        security_monitor.log_connection_event("SYSTEM_SHUTDOWN", "Enhanced trading system shutting down")
        logging.info(" Shutting down the enhanced system gracefully...")
        if client.is_connected():
            await client.disconnect()
        position_manager.stop()
        for handler in mt5_handlers:
            handler.disconnect_mt5()
        logging.info(" Enhanced system shutdown complete.")

if __name__ == "__main__":
    asyncio.run(main())