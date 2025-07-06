# test_parser.py
import logging
from pprint import pprint
from signal_parser import parse_signal

# Set up basic logging to see the parser's debug messages
logging.basicConfig(level=logging.DEBUG, format='%(levelname)s - %(message)s')

# ----------------- VERY IMPORTANT ----------------- #
# --- PASTE THE EXACT FAILING MESSAGE FROM TELEGRAM HERE --- #
message_to_test = """
-US100 SELL NOW

TP1: 21950.0

TP2: 21900.0

TP3: 21850.0

TP4: 21800.0

SL: 22100.0
"""
# ---------------------------------------------------- #


print("--- Running Parser Test ---")
print("Message to be parsed:")
print("=======================")
print(message_to_test)
print("=======================")
print("\nParser output:")

# Run the parser with the test message
parsed_result = parse_signal(message_to_test)

print("\n--- Test Result ---")
if parsed_result:
    print("✅ Signal Parsed Successfully!")
    pprint(parsed_result)
else:
    print("❌ Signal Parsing Failed. Check the DEBUG logs above to see which step failed.")
print("--- End of Test ---")