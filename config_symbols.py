# config_symbols.py

# This map converts signal names (keys) to broker names (values)
SYMBOL_MAP = {
    "US30": "US30Cash",
    "DJ30": "US30Cash",
    "DAX": "GER40Cash",
    "GER30": "GER40Cash",
    "GER40": "GER40Cash",
    "GOLD": "XAUUSD",
    "XAUUSD": "XAUUSD",
    "OIL": "OILCash",
    "USOIL": "OILCash",
    "NIKKEI": "JP225Cash",
    "US100": "US100Cash",
    # Add any other aliases you use
}

# This creates a reverse map for convenience if ever needed
REVERSE_SYMBOL_MAP = {v: k for k, v in SYMBOL_MAP.items()}