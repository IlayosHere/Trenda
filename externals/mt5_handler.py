import MetaTrader5 as mt5

def initialize_mt5():
    """Initializes and checks the MT5 connection."""
    if not mt5.initialize():
        print(f"MT5 initialization failed. Error: {mt5.last_error()}")
        return False
    print("✅ MT5 initialized successfully.")
    return True


def shutdown_mt5():
    print("Shutting down MT5 connection...")
    mt5.shutdown()
