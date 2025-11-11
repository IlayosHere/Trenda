from __future__ import annotations

import MetaTrader5 as mt5

from data_retriever.utils import display


def initialize_mt5() -> bool:
    """Initializes and checks the MT5 connection."""
    if not mt5.initialize():
        display.print_error(f"MT5 initialization failed. Error: {mt5.last_error()}")
        return False

    display.print_status("✅ MT5 initialized successfully.")
    return True


def shutdown_mt5() -> None:
    display.print_status("Shutting down MT5 connection...")
    mt5.shutdown()
