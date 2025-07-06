# partial_closing_manager.py
import MetaTrader5 as mt5
import time
import logging
import json
import os
from threading import Thread, RLock
from queue import Queue

class PartialClosingManager:
    def __init__(self, mt5_handlers, trading_settings):
        self.handlers = mt5_handlers
        self.settings = trading_settings
        self.state_file = "positions_state.json"
        self.lock = RLock()
        self._stop_event = False
        self.position_data = self._load_state()
        self.registration_queue = Queue()

    def _load_state(self):
        with self.lock:
            if os.path.exists(self.state_file):
                try:
                    with open(self.state_file, 'r') as f:
                        # Keys are loaded as strings from JSON, convert them back to int
                        return {int(k): v for k, v in json.load(f).items()}
                except (json.JSONDecodeError, ValueError) as e:
                    logging.error(f"Error loading state file '{self.state_file}': {e}. Starting with a fresh state.")
                    return {}
            return {}

    def _save_state(self):
        with self.lock:
            try:
                # To prevent race conditions, create a copy of the data to dump
                data_to_save = self.position_data.copy()
                with open(self.state_file, 'w') as f:
                    json.dump(data_to_save, f, indent=4)
            except Exception as e:
                logging.error(f"Could not write to state file '{self.state_file}': {e}")

    def start(self):
        logging.info("Partial Closing Manager started.")
        Thread(target=self.run, daemon=True).start()

    def stop(self):
        logging.info("Partial Closing Manager shutting down...")
        self._stop_event = True
        self._save_state() # Final save on shutdown

    def run(self):
        while not self._stop_event:
            try:
                # Get a fresh list of all active trades from all handlers
                open_positions, pending_orders = self._get_all_open_positions(), self._get_all_pending_orders()
                
                actions_to_perform = []
                state_changed = False
                
                with self.lock:
                    # Process any new trades that have been placed
                    if self._process_registration_queue():
                        state_changed = True
                    
                    # Remove any trades from our state that are no longer on the server
                    if self._cleanup_closed_trades(open_positions, pending_orders):
                        state_changed = True
                    
                    # Decide what actions to take on our managed positions
                    actions, needs_save = self._decide_on_position_actions(open_positions, pending_orders)
                    actions_to_perform.extend(actions)
                    if needs_save:
                        state_changed = True
                    
                    if state_changed:
                        self._save_state()

                # Execute all planned actions outside of the main lock
                if actions_to_perform:
                    secured_groups = set() # To ensure we only secure a group once per cycle
                    for action in actions_to_perform:
                        if action['type'] == 'close':
                            self._close_partial(action['position'], action['volume'], action['handler'])
                        elif action['type'] == 'secure_group':
                            group_id = action['group_id']
                            if group_id not in secured_groups:
                                self._secure_trade_group(group_id, open_positions)
                                self._cancel_pending_orders_for_group(group_id, pending_orders)
                                secured_groups.add(group_id)
                        elif action['type'] == 'close_ghost':
                            self._close_full(action['position'], action['handler'])

            except Exception as e:
                logging.error(f"FATAL ERROR in PartialClosingManager loop: {e}", exc_info=True)
            
            time.sleep(2) # Main loop delay

    def _process_registration_queue(self):
        changed = False
        while not self.registration_queue.empty():
            task = self.registration_queue.get()
            ticket = task['ticket']
            self.position_data[ticket] = {
                "account_login": task['account_login'],
                "signal": task['signal_data'],
                "original_volume": task['original_volume'],
                "closed_tps": [],
                "is_secured": False,
                "group_id": task['group_id'],
                "pending_close_volume": 0.0
            }
            logging.info(f"Order {ticket} (Group {task['group_id']}) registered for management.")
            changed = True
        return changed

    def _cleanup_closed_trades(self, current_positions, pending_orders):
        changed = False
        open_position_tickets = {pos.ticket for pos, _ in current_positions}
        pending_order_tickets = {o.ticket for o, _ in pending_orders if o}
        all_active_tickets = open_position_tickets.union(pending_order_tickets)

        # Check for ghost positions (in MT5 but not in our state)
        all_managed_tickets = set(self.position_data.keys())
        for pos, acc_login in current_positions:
            if pos.ticket not in all_managed_tickets:
                 logging.warning(f"GHOST POSITION DETECTED on account {acc_login}: ticket {pos.ticket}, symbol {pos.symbol}. Closing for safety.")
                 handler = self._find_handler_by_login(acc_login)
                 if handler:
                    self._close_full(pos, handler)

        # Remove trades from state if they no longer exist on the server
        for ticket in list(self.position_data.keys()):
            if ticket not in all_active_tickets:
                logging.info(f"Order/Position {ticket} (Group: {self.position_data[ticket].get('group_id')}) no longer active. Removing from management.")
                del self.position_data[ticket]
                changed = True
        return changed
        
    def _decide_on_position_actions(self, linked_positions, pending_orders):
        action_list, state_changed = [], False
        
        # Check which groups are already fully secured
        secured_groups = {
            p['group_id'] for p in self.position_data.values() 
            if p.get('is_secured') and p.get('group_id')
        }

        for pos, acc_login in linked_positions:
            if pos.ticket not in self.position_data:
                # This is handled by cleanup, but as a safeguard, we skip.
                continue

            pos_info = self.position_data[pos.ticket]
            group_id = pos_info.get('group_id')
            handler = self._find_handler_by_login(acc_login)
            if not handler: continue

            signal, symbol_info = pos_info['signal'], mt5.symbol_info(pos.symbol)
            if not symbol_info: continue

            tick = mt5.symbol_info_tick(pos.symbol)
            if not tick: continue
            
            current_price = tick.bid if pos.type == mt5.ORDER_TYPE_SELL else tick.ask
            
            for i, tp_level in enumerate(signal['tps']):
                tp_num = i + 1
                if tp_num in pos_info.get('closed_tps', []):
                    continue

                is_hit = False
                pip_size = handler.get_symbol_pip_info(pos.symbol)
                # Buffer only applies to TP1 for securing, not for closing
                buffer_amount = self.settings.get('secure_tp1_pips_buffer', 0) * pip_size if pip_size and tp_num == 1 else 0

                if pos.type == mt5.ORDER_TYPE_BUY and current_price >= (tp_level - buffer_amount):
                    is_hit = True
                elif pos.type == mt5.ORDER_TYPE_SELL and current_price <= (tp_level + buffer_amount):
                    is_hit = True

                if is_hit:
                    logging.info(f"TP{tp_num} ({tp_level}) HIT for position {pos.ticket} at price {current_price}.")
                    pos_info.setdefault('closed_tps', []).append(tp_num)
                    volume_per_tp = round(pos_info['original_volume'] / signal['num_tps'], 2)
                    
                    # Schedule a partial close action
                    action_list.append({'type': 'close', 'position': pos, 'volume': volume_per_tp, 'handler': handler})
                    
                    state_changed = True
                    
                    # If TP1 is hit and the group isn't already secured, plan to secure it
                    if tp_num == 1 and group_id and group_id not in secured_groups:
                        logging.info(f"TP1 hit triggers securing for entire group {group_id}.")
                        action_list.append({'type': 'secure_group', 'group_id': group_id})
                        secured_groups.add(group_id) # Mark as planned for securing
                    
                    break # Move to the next position after one TP hit
        return action_list, state_changed

    def _secure_trade_group(self, group_id, all_open_positions):
        logging.info(f"Executing securing action for group {group_id}.")
        for pos, acc_login in all_open_positions:
            pos_info = self.position_data.get(pos.ticket)
            if pos_info and pos_info.get('group_id') == group_id and not pos_info.get('is_secured'):
                handler = self._find_handler_by_login(acc_login)
                if handler:
                    self._secure_position(pos, handler)

    def _cancel_pending_orders_for_group(self, group_id, all_pending_orders):
        logging.info(f"Cancelling pending orders for secured group {group_id}.")
        for order, acc_login in all_pending_orders:
            order_info = self.position_data.get(order.ticket)
            if order_info and order_info.get('group_id') == group_id:
                handler = self._find_handler_by_login(acc_login)
                if handler:
                    self._delete_pending_order(order.ticket, handler)

    def _secure_position(self, position, handler):
        with handler.lock:
            # Secure by moving SL to the open price
            secure_sl_price = position.price_open
            
            request = {"action": mt5.TRADE_ACTION_SLTP, "position": position.ticket, "sl": secure_sl_price, "tp": position.tp}
            result = mt5.order_send(request)
            
            # CRITICAL: Only change the state AFTER successful execution
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                logging.info(f"Successfully secured position {position.ticket} by moving SL to {secure_sl_price}.")
                # Now, lock the state and flip the flag to prevent retries.
                with self.lock:
                    if position.ticket in self.position_data:
                        self.position_data[position.ticket]['is_secured'] = True
            else:
                err = mt5.last_error() if not result else result.comment
                logging.error(f"Failed to secure position {position.ticket}. Will retry. Error: {err}")
    
    def _get_all_open_positions(self):
        linked_positions = []
        for handler in self.handlers:
            if handler._connected:
                with handler.lock:
                    positions = mt5.positions_get(login=handler.config['login'])
                    if positions:
                        for pos in positions:
                            linked_positions.append((pos, handler.config['login']))
        return linked_positions

    def _get_all_pending_orders(self):
        all_orders = []
        for handler in self.handlers:
            if handler._connected:
                with handler.lock:
                    orders = mt5.orders_get(login=handler.config['login'])
                    if orders:
                        for order in orders:
                            all_orders.append((order, handler.config['login']))
        return all_orders

    def _find_handler_by_login(self, login_id):
        for handler in self.handlers:
            if handler.config.get('login') == login_id:
                return handler
        return None

    def _close_full(self, position, handler):
        self._close_partial(position, position.volume, handler)

    def _delete_pending_order(self, ticket_id, handler):
        with handler.lock:
            request = {"action": mt5.TRADE_ACTION_REMOVE, "order": ticket_id}
            result = mt5.order_send(request)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                 logging.info(f"Successfully deleted pending order {ticket_id}.")
            else:
                 err = mt5.last_error() if not result else result.comment
                 logging.error(f"Failed to delete pending order {ticket_id}. Error: {err}")

    def _close_partial(self, position, volume_to_close, handler):
        if volume_to_close <= 0: return
        
        with handler.lock:
            # Ensure volume is valid before sending
            symbol_info = mt5.symbol_info(position.symbol)
            if not symbol_info:
                logging.error(f"Cannot close {position.ticket}, failed to get symbol info.")
                return
            
            # Ensure volume is a multiple of step and not too small
            volume_to_close = max(volume_to_close, symbol_info.volume_min)
            volume_to_close = round(volume_to_close / symbol_info.volume_step) * symbol_info.volume_step
            # Don't close more than what's open
            volume_to_close = min(volume_to_close, position.volume)
            
            if volume_to_close < symbol_info.volume_min:
                logging.warning(f"Calculated close volume {volume_to_close} for {position.ticket} is less than min {symbol_info.volume_min}. Aborting close.")
                return

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "position": position.ticket,
                "symbol": position.symbol,
                "volume": volume_to_close,
                "type": mt5.ORDER_TYPE_SELL if position.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY,
                "magic": handler.config['login'],
                "type_filling": handler.get_filling_mode(position.symbol)
            }
            result = mt5.order_send(request)
            
            if not (result and result.retcode == mt5.TRADE_RETCODE_DONE):
                err = mt5.last_error() if not result else result.comment
                logging.error(f"Failed to close partial volume for {position.ticket}. Volume: {volume_to_close}. Error: {err}")
            else:
                 logging.info(f"Successfully closed {volume_to_close} lots for position {position.ticket}.")