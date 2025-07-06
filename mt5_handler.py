# mt5_handler.py
import MetaTrader5 as mt5
import time
import logging
from threading import Lock
from config_symbols import SYMBOL_MAP
import math

class MT5Handler:
    def __init__(self, account_config, trading_settings, position_manager):
        print(f"--- [Handler {account_config.get('login')}] Initializing MT5Handler object ---")
        self.config = account_config
        self.settings = trading_settings
        self.position_manager = position_manager
        self.lock = Lock()
        self._connected = False
        if not self.connect_mt5():
            # This exception will be caught in main.py
            raise ConnectionError(f"Failed to connect to MT5 account {self.config['login']}")

    def connect_mt5(self):
        print(f"--- [Handler {self.config['login']}] Entering connect_mt5 method ---")
        logging.info(f"Attempting to connect to MT5 account {self.config['login']}...")
        with self.lock:
            for i in range(3):
                print(f"--- [Handler {self.config['login']}] Connection attempt {i+1}/3 ---")
                
                # --- THIS IS THE MOST LIKELY POINT OF FAILURE ---
                print(f"--- [Handler {self.config['login']}] Calling mt5.initialize() with path: '{self.config['terminal_path']}' ---")
                initialized = mt5.initialize(
                    path=self.config['terminal_path'], 
                    login=self.config['login'], 
                    password=self.config['password'], 
                    server=self.config['server']
                )
                print(f"--- [Handler {self.config['login']}] mt5.initialize() returned: {initialized} ---")
                # --- END OF DANGER ZONE ---

                if initialized:
                    print(f"--- [Handler {self.config['login']}] Initialization successful. Checking account info... ---")
                    if mt5.account_info():
                        print(f"--- [Handler {self.config['login']}] Connection SUCCESSFUL ---")
                        logging.info(f"Connection successful to account {self.config['login']}.")
                        self._connected = True
                        return True
                    else:
                        print(f"--- [Handler {self.config['login']}] Initialization succeeded, but could not get account info. ---")
                
                print(f"--- [Handler {self.config['login']}] Initialization failed. Last error: {mt5.last_error()} ---")
                logging.error(f"MT5 initialize failed for {self.config['login']} (Attempt {i+1}/3). Error: {mt5.last_error()}")
                time.sleep(2)
        return False

    def disconnect_mt5(self):
        if self._connected:
            mt5.shutdown()
            logging.info(f"Disconnected from account {self.config['login']}.")

    def get_filling_mode(self, symbol):
        try:
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is None:
                logging.warning(f"Could not get symbol info for {symbol}. Falling back to IOC.")
                return mt5.ORDER_FILLING_IOC
            return mt5.ORDER_FILLING_IOC
        except Exception as e:
            logging.error(f"Error determining filling mode for {symbol}: {e}. Defaulting to IOC.")
            return mt5.ORDER_FILLING_IOC

    def get_symbol_pip_info(self, broker_symbol):
        symbol_info = mt5.symbol_info(broker_symbol)
        if not symbol_info:
            logging.warning(f"Could not get symbol info for {broker_symbol}.")
            return None
        if "CASH" in broker_symbol.upper() or "JP225" in broker_symbol.upper() or symbol_info.digits <= 1:
            return 1.0
        if "JPY" in broker_symbol.upper():
            return 0.01
        if "XAU" in broker_symbol.upper() and symbol_info.digits in [2, 3]:
            return 0.01
        if symbol_info.digits in [4, 5]:
            return 0.0001
        logging.warning(f"Pip rule not found for {broker_symbol} (digits: {symbol_info.digits}), falling back to '10 * point'.")
        return 10 * symbol_info.point

    def calculate_lot_size(self, signal, entry_price, sl_price):
        """
        Calculates an order volume that is both risk-compliant and perfectly divisible 
        by the number of TPs, respecting broker minimums.
        """
        account_info = mt5.account_info()
        if not account_info:
            logging.error("Failed to get account info for lot calculation.")
            return None

        risk_amount = account_info.balance * (self.settings['risk_per_trade_percent'] / 100.0)
        symbol = signal['symbol']
        num_tps = signal['num_tps']
        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info:
             logging.error(f"Failed to get symbol_info for {symbol} in lot calculation.")
             return None

        raw_total_volume = 0.0
        sl_distance = abs(entry_price - sl_price)
        if sl_distance == 0:
            logging.error(f"Stop loss distance is zero for {symbol}. Cannot calculate lot size.")
            return None
            
        tick_value = symbol_info.trade_tick_value
        tick_size = symbol_info.trade_tick_size
        if tick_value is None or tick_size is None or tick_size == 0:
            logging.error(f"Invalid tick value/size for {symbol}. Cannot calculate lot size.")
            return None

        value_per_point = tick_value / tick_size
        risk_per_lot = sl_distance * value_per_point
        if risk_per_lot == 0:
            logging.error(f"Risk per lot is zero for {symbol}. Cannot calculate lot size.")
            return None

        raw_total_volume = risk_amount / risk_per_lot

        if num_tps <= 0: num_tps = 1
        volume_min = symbol_info.volume_min
        volume_step = symbol_info.volume_step
        
        raw_volume_per_tp = raw_total_volume / num_tps
        adjusted_volume_per_tp = max(raw_volume_per_tp, volume_min)
        final_volume_per_tp = math.ceil(adjusted_volume_per_tp / volume_step) * volume_step
        final_total_volume = final_volume_per_tp * num_tps
        final_total_volume = min(symbol_info.volume_max, final_total_volume)
        
        if final_total_volume < volume_min:
            logging.warning(f"Calculated lot {final_total_volume:.2f} for {symbol} is below minimum {volume_min}. Adjusting to minimum.")
            final_total_volume = volume_min

        logging.info(f"Volume for {self.config['login']} ({symbol}): Risk={risk_amount:.2f}, SL Dist={sl_distance}, Raw Vol={raw_total_volume:.4f}, Final Vol={final_total_volume:.2f} ({final_volume_per_tp:.2f} per TP over {num_tps} TPs)")
        return round(final_total_volume, 2)

    def execute_trade(self, signal):
        with self.lock:
            logging.info(f"Account {self.config['login']}: Processing {len(signal['entries'])} entries for signal group {signal['group_id']}...")
            for entry in signal['entries']:
                self._execute_single_order(signal, entry)
            logging.info(f"Account {self.config['login']}: Finished processing entries for {signal['group_id']}.")

    def _execute_single_order(self, signal, entry_info):
        symbol, direction, sl, final_tp = signal['symbol'], signal['direction'], signal['sl'], signal['final_tp']
        
        order_type_map = {"BUY": mt5.ORDER_TYPE_BUY, "SELL": mt5.ORDER_TYPE_SELL, "BUY_LIMIT": mt5.ORDER_TYPE_BUY_LIMIT, "SELL_LIMIT": mt5.ORDER_TYPE_SELL_LIMIT, "BUY_STOP": mt5.ORDER_TYPE_BUY_STOP, "SELL_STOP": mt5.ORDER_TYPE_SELL_STOP}
        entry_type_key = f"{direction}_{entry_info['type']}" if entry_info['type'] != 'MARKET' else direction
        trade_type = order_type_map.get(entry_type_key)
        
        if trade_type is None:
            logging.error(f"Invalid entry type key generated: {entry_type_key}")
            return

        entry_price = entry_info['price']
        if entry_info['type'] == 'MARKET':
             tick = mt5.symbol_info_tick(symbol)
             if not tick:
                 logging.error(f"Could not get tick for {symbol} to place market order.")
                 return
             entry_price = tick.ask if direction == "BUY" else tick.bid
        
        volume = self.calculate_lot_size(signal, entry_price, sl)
        if not volume or volume <= 0:
            logging.error(f"Invalid volume calculated ({volume}) for {symbol}. Order cancelled.")
            return

        filling_mode = self.get_filling_mode(symbol)
        request = {
            "action": mt5.TRADE_ACTION_DEAL if entry_info['type'] == 'MARKET' else mt5.TRADE_ACTION_PENDING,
            "symbol": symbol, "volume": volume, "type": trade_type, "sl": sl, "tp": final_tp,
            "magic": self.config['login'], "comment": f"GID:{signal['group_id']}",
            "type_time": mt5.ORDER_TIME_GTC, "type_filling": filling_mode
        }
        if entry_info['type'] != 'MARKET':
            request["price"] = entry_info['price']
            
        result = mt5.order_send(request)

        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            logging.info(f"Order sent successfully. Account: {self.config['login']}, Ticket: {result.order}, Type: {entry_type_key}, Symbol: {symbol}")
            registration_task = {
                "ticket": result.order, "account_login": self.config['login'],
                "signal_data": signal, "original_volume": volume, "group_id": signal['group_id']
            }
            self.position_manager.registration_queue.put(registration_task)
        else:
            error_code = result.retcode if result else 'N/A'
            error_comment = mt5.last_error() if not result else result.comment
            logging.error(f"Order FAILED on Account {self.config['login']}! Symbol: {symbol}, Type: {entry_type_key}. Code: {error_code}, Comment: {error_comment}")