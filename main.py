# main.py
import json
import logging
import asyncio
import os
import sys # <-- Import the sys module
from telethon import TelegramClient, events
from signal_parser import parse_signal
from mt5_handler import MT5Handler
from partial_closing_manager import PartialClosingManager

# --- Setup Logging ---
LOGS_DIR = 'logs'
if not os.path.exists(LOGS_DIR):
    os.makedirs(LOGS_DIR)

# --- THIS IS THE MODIFIED BLOCK ---
# We explicitly tell the StreamHandler to use sys.stdout for INFO logs,
# which prevents them from being labeled as errors by script_keeper.py.
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(module)s:%(lineno)d] - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOGS_DIR, "trading_system.log")),
        logging.StreamHandler(sys.stdout) # <--- THIS IS THE CHANGE
    ]
)
# Reduce verbosity of the telethon library
logging.getLogger('telethon').setLevel(logging.WARNING)


async def main():
    """Main function to initialize and run the trading system."""
    try:
        with open('config.json') as f:
            config = json.load(f)
        logging.info("Configuration loaded successfully.")
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logging.critical(f"Critical error loading config.json: {e}. System cannot start.")
        return

    # --- Initialize MT5 and Position Manager (Done once at the start) ---
    mt5_handlers = []
    position_manager = PartialClosingManager([], config['trading_settings'])
    
    for account_config in config.get('accounts', []):
        try:
            handler = MT5Handler(account_config, config['trading_settings'], position_manager)
            mt5_handlers.append(handler)
        except ConnectionError as e:
            logging.error(f"Could not start handler for account {account_config.get('login', 'N/A')}: {e}")
    
    if not mt5_handlers:
        logging.critical("No MT5 accounts connected. The system will not execute trades. Exiting.")
        return

    position_manager.handlers = mt5_handlers
    position_manager.start()

    # --- Main Reconnection Loop for Telegram ---
    telegram_config = config['telegram']
    client = TelegramClient(
        telegram_config['session_name'],
        telegram_config['api_id'],
        telegram_config['api_hash']
    )

    @client.on(events.NewMessage(chats=telegram_config['target_channel_ids']))
    async def new_message_handler(event):
        logging.info(f"--- New Message Received from Channel {event.chat_id} ---")
        message_text = event.message.message
        
        if parsed_signal := parse_signal(message_text):
            logging.info(f"Signal parsed for {parsed_signal['symbol']}. Distributing to all active MT5 handlers.")
            tasks = [asyncio.to_thread(handler.execute_trade, parsed_signal) for handler in mt5_handlers]
            await asyncio.gather(*tasks, return_exceptions=True)
        else:
            logging.warning("Message did not contain a valid/parsable signal.")

    try:
        while True:
            try:
                logging.info("Attempting to connect to Telegram...")
                await client.start()
                logging.info("Telegram client connected successfully. Listening for signals...")
                await client.run_until_disconnected()
            
            except (ConnectionError, TimeoutError) as e:
                logging.warning(f"Telegram connection lost: {e}. The client will attempt to reconnect automatically.")
                await asyncio.sleep(60)
            
            except Exception as e:
                logging.critical(f"An unexpected critical error occurred with the Telegram client: {e}", exc_info=True)
                logging.info("Attempting to recover and reconnect in 60 seconds...")
                if client.is_connected():
                    await client.disconnect()
                await asyncio.sleep(60)
    
    except (KeyboardInterrupt, SystemExit):
        logging.info("System interruption detected (e.g., Ctrl+C).")
    
    finally:
        logging.info("Shutting down the system gracefully...")
        if client.is_connected():
            await client.disconnect()
        position_manager.stop()
        for handler in mt5_handlers:
            handler.disconnect_mt5()
        logging.info("System shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())