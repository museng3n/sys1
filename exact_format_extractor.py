import re
import csv
import json
import asyncio
from datetime import datetime, timezone, timedelta, date
from telethon import TelegramClient, errors
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.tl.types import InputPeerChannel, InputPeerUser, PeerChannel

# DELETEME - This indicator is here for you to find and remove later as requested

class TelegramSignalExtractor:
    def __init__(self, api_id, api_hash, phone, channel_ids=None):
        """
        Initialize the Telegram Signal Extractor
        
        Parameters:
        api_id (int): Telegram API ID from https://my.telegram.org/
        api_hash (str): Telegram API Hash from https://my.telegram.org/
        phone (str): Your phone number with country code (e.g., +1234567890)
        channel_ids (list): List of channel IDs to extract signals from
        """
        self.api_id = api_id
        self.api_hash = api_hash
        self.phone = phone
        self.channel_ids = channel_ids or []
        self.client = None
        self.signals = []
        
    async def connect(self):
        """Connect to Telegram API"""
        self.client = TelegramClient('signal_session', self.api_id, self.api_hash)
        await self.client.start(self.phone)
        print("Connected to Telegram")
        
    async def extract_signals(self, channel_id, limit=1000, start_date=None, end_date=None, timezone_offset=3):
        """
        Extract trading signals from a specific channel within a date range
        
        Parameters:
        channel_id (int): Telegram channel ID
        limit (int): Maximum number of messages to extract
        start_date (str): Start date in format 'YYYY-MM-DD HH:MM:SS'
        end_date (str): End date in format 'YYYY-MM-DD HH:MM:SS'
        timezone_offset (int): Hours offset from UTC (positive for east, negative for west)
        
        Returns:
        list: Extracted trading signals
        """
        if not self.client:
            raise ValueError("Not connected to Telegram. Call connect() first.")
            
        channel_signals = []
        
        # Add maximum age filter
        MAX_SIGNAL_AGE_HOURS = 24  # Only process signals from last 24 hours
        current_time = datetime.now(timezone.utc)
        
        # Convert date strings to datetime objects if provided
        start_datetime = None
        end_datetime = None
        
        if start_date:
            # Parse local time and convert to UTC for comparison with Telegram times
            local_start = datetime.strptime(start_date, '%Y-%m-%d %H:%M:%S')
            # Convert to UTC by subtracting the timezone offset
            start_datetime = local_start.replace(tzinfo=timezone.utc) - timedelta(hours=timezone_offset)
            print(f"Filtering messages from {start_date} (local) / {start_datetime} (UTC)")
            
        if end_date:
            # Parse local time and convert to UTC for comparison with Telegram times
            local_end = datetime.strptime(end_date, '%Y-%m-%d %H:%M:%S')
            # Convert to UTC by subtracting the timezone offset
            end_datetime = local_end.replace(tzinfo=timezone.utc) - timedelta(hours=timezone_offset)
            print(f"Filtering messages until {end_date} (local) / {end_datetime} (UTC)")
        
        try:
            # Get the channel entity
            channel_entity = await self.client.get_entity(PeerChannel(channel_id))
            
            # Get channel messages
            posts = await self.client(GetHistoryRequest(
                peer=channel_entity,
                limit=limit,
                offset_date=end_datetime,  # Start from end_date if specified
                offset_id=0,
                max_id=0,
                min_id=0,
                add_offset=0,
                hash=0
            ))
            
            print(f"Retrieved {len(posts.messages)} messages from channel {channel_id}")
            
            # Process each message
            for message in posts.messages:
                if not message.message:
                    continue
                
                # Check message age
                message_age = current_time - message.date
                if message_age.total_seconds() > (MAX_SIGNAL_AGE_HOURS * 3600):
                    print(f"Skipping old message from {message.date} (older than {MAX_SIGNAL_AGE_HOURS} hours)")
                    continue
                
                # Print message date for debugging
                print(f"Processing message at {message.date}: {message.message[:50]}...")
                
                # Skip messages outside the date range - STRICTLY check dates
                if start_datetime and message.date < start_datetime:
                    print(f"Skipping message: before start date ({start_datetime})")
                    continue
                    
                if end_datetime and message.date > end_datetime:
                    print(f"Skipping message: after end date ({end_datetime})")
                    continue
                
                # Print full message for debugging (only first few)
                if len(channel_signals) < 3:  # Only for the first 3 signals we find
                    print(f"FULL MESSAGE:\n{message.message}")
                
                # Parse signal message
                signal = self.parse_signal_message(message.message)
                if signal:
                    print(f"Found signal: {signal['symbol']} {signal['direction']}")
                    # Add message metadata
                    signal['timestamp'] = message.date.isoformat()
                    signal['message_id'] = message.id
                    signal['channel_id'] = channel_id
                    signal['message_age_hours'] = message_age.total_seconds() / 3600
                    channel_signals.append(signal)
                else:
                    print(f"Message does not match signal pattern")
            
            print(f"Extracted {len(channel_signals)} trading signals from channel {channel_id} within the date range")
            self.signals.extend(channel_signals)
            return channel_signals
            
        except errors.rpcerrorlist.ChannelPrivateError:
            print(f"Cannot access private channel {channel_id}. Make sure the account is a member.")
        except Exception as e:
            print(f"Error extracting signals from channel {channel_id}: {e}")
            
        return []
         
    def parse_signal_message(self, message_text):
        """
        Parse a message to extract trading signal information
        
        Parameters:
        message_text (str): Raw message text from Telegram
        
        Returns:
        dict: Parsed signal data or None if not a signal
        """
        # Pattern to match trading signals like the examples - more permissive version
        english_pattern = r'((?:US30|US100|DAX\s*40|NIKKEI|GOLD|[A-Za-z0-9]{3,8}))\s+(BUY|SELL)\s+(NOW|limit from\s+[\d.]+).*?(?:Tp1|Tp\s*1)'
        
        match = re.search(english_pattern, message_text, re.DOTALL | re.IGNORECASE)
        if match:
            # Find the start position of the English part
            start_pos = match.start()
            
            # Extract the entire English signal section - starts with currency pair and ends with stop loss
            english_section = message_text[start_pos:]
            
            # Find the end of the signal (after the stop loss line)
            sl_pattern = r'(?:Sl|SI)\s*@\s*[\d.]+'
            sl_match = re.search(sl_pattern, english_section, re.IGNORECASE)
            if sl_match:
                # Get position after the stop loss
                end_pos = sl_match.end()
                
                # Find the next line break after stop loss, if any
                next_line_break = english_section.find('\n', end_pos)
                if next_line_break != -1:
                    # Use the line break to end the signal
                    english_section = english_section[:next_line_break]
                else:
                    # Use a bit more after stop loss to capture any trailing elements
                    english_section = english_section[:end_pos + 10]
            
            # Clean up the extracted signal - remove any line-ending emojis
            cleaned_lines = []
            for line in english_section.split('\n'):
                # Remove emojis and other special characters at end of line
                clean_line = re.sub(r'[^\x00-\x7F]+$', '', line.strip())
                if clean_line:  # Only add non-empty lines
                    cleaned_lines.append(clean_line)
            
            # Recreate the clean signal text
            signal_text = '\n'.join(cleaned_lines)
            print(f"Extracted signal format:\n{signal_text}")
            
            # Extract basic info
            symbol = match.group(1).strip()  # Ensure we strip any extra spaces
            direction = match.group(2)
            
            # Create signal dictionary
            signal = {
                'symbol': symbol,
                'direction': direction,
                'raw_message': signal_text  # Clean English part only
            }
            
            # Check if it's a market or limit order
            if 'NOW' in signal_text.upper():
                signal['entry_type'] = 'market'
                signal['entry_points'] = ['market']
            else:
                signal['entry_type'] = 'limit'
                # Extract entry points
                entry_pattern = r'limit from\s+([\d.]+)'  
                entries = []
                for e in re.findall(entry_pattern, signal_text, re.IGNORECASE):
                    try:
                        # Clean the entry value (remove extra dots, spaces)
                        clean_e = e.strip().lstrip('.')
                        entries.append(float(clean_e))
                    except ValueError:
                        print(f"Warning: Could not parse entry value: '{e}', skipping...")
                        continue
                signal['entry_points'] = entries
                
                # Check for second direction
                if 'and ' in signal_text:
                    second_dir_match = re.search(r'and\s+(BUY|SELL)', signal_text, re.IGNORECASE)
                    if second_dir_match:
                        signal['direction2'] = second_dir_match.group(1)
            
            # Extract take profit targets
            tp_pattern = r'Tp\s*(\d+)\s*@\s*([\d.]+)'
            take_profits = {}
            for tp_match in re.findall(tp_pattern, signal_text, re.IGNORECASE):
                tp_num = int(tp_match[0])
                tp_value = float(tp_match[1])
                take_profits[f'tp{tp_num}'] = tp_value
            signal['take_profits'] = take_profits
            
            # Extract stop loss - handle both Sl and SI formats
            sl_pattern = r'(?:Sl|SI)\s*@\s*([\d.]+)'
            sl_match = re.search(sl_pattern, signal_text, re.IGNORECASE)
            if sl_match:
                signal['stop_loss'] = float(sl_match.group(1))
                
            return signal
        
        return None
    
    async def extract_all_channels(self, limit=1000, start_date=None, end_date=None, timezone_offset=3):
        """
        Extract signals from all configured channels within a date range
        
        Parameters:
        limit (int): Maximum number of messages to extract per channel
        start_date (str): Start date in format 'YYYY-MM-DD HH:MM:SS'
        end_date (str): End date in format 'YYYY-MM-DD HH:MM:SS'
        timezone_offset (int): Hours offset from UTC (positive for east, negative for west)
        
        Returns:
        list: All extracted signals
        """
        self.signals = []
        for channel_id in self.channel_ids:
            await self.extract_signals(channel_id, limit, start_date, end_date, timezone_offset)
        return self.signals
    
    def export_to_csv(self, filename):
        """
        Export extracted signals to CSV file
        
        Parameters:
        filename (str): Output file name
        """
        if not self.signals:
            print("No signals to export")
            return
            
        try:
            # Determine all keys for CSV headers
            headers = set()
            for signal in self.signals:
                headers.update(signal.keys())
                if 'take_profits' in signal:
                    headers.update(signal['take_profits'].keys())
            
            # Remove complex fields that will be flattened
            if 'take_profits' in headers:
                headers.remove('take_profits')
                
            headers = sorted(list(headers))
            
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=headers)
                writer.writeheader()
                
                for signal in self.signals:
                    # Flatten take_profits into the main dictionary
                    row = signal.copy()
                    if 'take_profits' in row:
                        for tp_key, tp_value in row['take_profits'].items():
                            row[tp_key] = tp_value
                        del row['take_profits']
                        
                    writer.writerow(row)
                    
            print(f"Exported {len(self.signals)} signals to {filename}")
            
        except Exception as e:
            print(f"Error exporting to CSV: {e}")
    
    def export_to_json(self, filename):
        """
        Export extracted signals to JSON file
        
        Parameters:
        filename (str): Output file name
        """
        if not self.signals:
            print("No signals to export")
            return
            
        try:
            with open(filename, 'w', encoding='utf-8') as jsonfile:
                json.dump(self.signals, jsonfile, indent=4)
                
            print(f"Exported {len(self.signals)} signals to {filename}")
            
        except Exception as e:
            print(f"Error exporting to JSON: {e}")
    
    async def post_signal_to_channel(self, channel_id, signal):
        """
        Post a formatted trading signal to a Telegram channel
        
        Parameters:
        channel_id (int): Telegram channel ID to post to
        signal (dict): Signal data to post
        
        Returns:
        bool: True if successful, False otherwise
        """
        if not self.client:
            raise ValueError("Not connected to Telegram. Call connect() first.")
            
        try:
            # Format the signal in the requested format
            formatted_signal = self.format_signal_for_posting(signal)
            
            # Get the channel entity
            channel_entity = await self.client.get_entity(PeerChannel(channel_id))
            
            # Post the message
            await self.client.send_message(channel_entity, formatted_signal)
            print(f"Posted signal {signal['symbol']} {signal['direction']} to channel {channel_id}")
            return True
            
        except Exception as e:
            print(f"Error posting signal to channel {channel_id}: {e}")
            return False
            
    def format_signal_for_posting(self, signal):
        """
        Format a signal dictionary into a text message for posting
        
        Parameters:
        signal (dict): Signal data dictionary
        
        Returns:
        str: Formatted signal text using the original raw message
        """
        # Simply return the raw message that was extracted
        # This ensures we maintain the exact original format
        return signal['raw_message']
    
    async def close(self):
        """Close the Telegram client connection"""
        if self.client:
            await self.client.disconnect()
            print("Disconnected from Telegram")


# Example usage
async def main():
    # Load secure credentials
    from secure_config import load_secure_config
    config = load_secure_config()
    API_ID = config['telegram']['api_id']
    API_HASH = config['telegram']['api_hash']
    PHONE = '009647738196037'
        
    # Channel IDs to extract from
    CHANNEL_IDS = [-1001552516320]  # Add more channel IDs as needed
    
    # Initialize the extractor
    extractor = TelegramSignalExtractor(API_ID, API_HASH, PHONE, CHANNEL_IDS)
    
    try:
        # Connect to Telegram
        await extractor.connect()
        
        # DELETEME - Automatic Date Range Calculation for Sunday to Monday
        # Calculate the most recent Monday
        today = datetime.now().date()
        days_since_monday = today.weekday()  # Monday is 0, Sunday is 6

        # If today is Monday, use today; otherwise find the last or next Monday
        if days_since_monday == 0:
            # Today is Monday
            target_monday = today
        elif days_since_monday == 6:
            # Today is Sunday, use tomorrow as target Monday
            target_monday = today + timedelta(days=1)
        else:
            # Use the most recent Monday
            target_monday = today - timedelta(days=days_since_monday)
            
            # For 2025 testing, uncomment this line:
            # target_monday = date(2025, 4, 8)  # This is a Monday in April 2025
        
        # Get the Sunday before the target Monday
        target_sunday = target_monday - timedelta(days=1)

        # Set start time to Sunday at 23:00
        START_DATE = f"{target_sunday} 23:00:00"

        # Set end time to Tuesday (day after Monday) at 01:00
        target_tuesday = target_monday + timedelta(days=1)
        END_DATE = f"{target_tuesday} 01:00:00"

        print(f"Automatically using date range: {START_DATE} to {END_DATE}")
        print(f"This covers Sunday evening through Monday night")
        
        TIMEZONE_OFFSET = 3  # Iraq is UTC+3
        
        # Channel ID for posting signals
        POST_CHANNEL_ID = -1002829694946
        
        # Extract signals from all channels within date range with increased message limit
        signals = await extractor.extract_all_channels(
            limit=5000,                      # Increased message limit significantly
            start_date=START_DATE, 
            end_date=END_DATE,
            timezone_offset=TIMEZONE_OFFSET  # Account for timezone difference
        )
        
        # Post signals to the target channel
        if signals:
            print(f"Posting {len(signals)} signals to channel {POST_CHANNEL_ID}...")
            for signal in signals:
                await extractor.post_signal_to_channel(POST_CHANNEL_ID, signal)
        else:
            print("No signals found to post.")
            
            # Post example signals if no real ones were found
            example_signals = [
                {
                    'symbol': 'GOLD',
                    'direction': 'BUY',
                    'entry_type': 'limit',
                    'entry_points': [2950, 2940],
                    'direction2': 'BUY',
                    'take_profits': {'tp1': 2960, 'tp2': 2970, 'tp3': 2980, 'tp4': 2990},
                    'stop_loss': 2930,
                    'sl_level': 'V',
                    'raw_message': """GOLD BUY limit from 2950 and BUY limit from 2940
Tp1 @ 2960 | 1
Tp2 @ 2970 2
Tp3 @ 2980 3
Tp4 @ 2990 4
SI @ 2930 V"""
                },
                {
                    'symbol': 'US100',
                    'direction': 'SELL',
                    'entry_type': 'limit',
                    'entry_points': [20000, 20200],
                    'direction2': 'SELL',
                    'take_profits': {'tp1': 19800, 'tp2': 19500, 'tp3': 19200, 'tp4': 18900},
                    'stop_loss': 20400,
                    'sl_level': '0',
                    'raw_message': """US100 SELL limit from 20000 and SELL limit from 20200
Tp1 @ 19800 | 1
Tp2 @ 19500 2
Tp3 @ 19200 3
Tp4 @ 18900 0
SI @ 20400"""
                }
            ]
            
            print("Posting example signals instead...")
            for signal in example_signals:
                await extractor.post_signal_to_channel(POST_CHANNEL_ID, signal)
        
        # Export to CSV and JSON
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        extractor.export_to_csv(f"trading_signals_{timestamp}.csv")
        extractor.export_to_json(f"trading_signals_{timestamp}.json")
        
    finally:
        # Close the connection
        await extractor.close()

if __name__ == "__main__":
    # Run the main function
    asyncio.run(main())