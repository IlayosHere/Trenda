"""Quick test script to simulate live trading for one symbol."""

import sys
sys.path.insert(0, '.')

# Load environment variables first
from dotenv import load_dotenv
load_dotenv('../.env')

from configuration import TIMEFRAMES, require_analysis_params
from entry.detector import _process_symbol, _FailureContext
from externals.meta_trader import initialize_mt5, mt5
from database.connection import DBConnectionManager
from logger import get_logger

logger = get_logger(__name__)

# Test configuration
TEST_SYMBOL = "EURUSD"
TIMEFRAME = "1H"
TREND_ALIGNMENT_TFS = ("4H", "1D", "1W")


def check_failed_signals_table():
    """Check recent entries in failed_signals table."""
    try:
        with DBConnectionManager.get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, symbol, failed_signal_time, failed_gate, fail_reason, reference_price
                    FROM trenda.failed_signals
                    ORDER BY id DESC
                    LIMIT 5
                """)
                rows = cur.fetchall()
                
                if rows:
                    print("\n📊 Recent failed_signals entries:")
                    print("-" * 80)
                    for row in rows:
                        print(f"  ID: {row[0]} | {row[1]} | {row[2]} | {row[3]}")
                        print(f"    Reason: {row[4]}")
                        print(f"    Ref Price: {row[5]}")
                        print()
                else:
                    print("\n📊 No entries in failed_signals table yet")
    except Exception as e:
        print(f"❌ Database error: {e}")


def check_entry_signals_table():
    """Check recent entries in entry_signal table."""
    try:
        with DBConnectionManager.get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, symbol, signal_time, direction, entry_price, actual_rr, price_drift
                    FROM trenda.entry_signal
                    ORDER BY id DESC
                    LIMIT 5
                """)
                rows = cur.fetchall()
                
                if rows:
                    print("\n📈 Recent entry_signal entries:")
                    print("-" * 80)
                    for row in rows:
                        print(f"  ID: {row[0]} | {row[1]} | {row[2]} | {row[3]}")
                        print(f"    Entry: {row[4]} | Actual RR: {row[5]} | Price Drift: {row[6]}")
                        print()
                else:
                    print("\n📈 No entries in entry_signal table yet")
    except Exception as e:
        print(f"❌ Database error: {e}")


def run_test():
    """Run the detector for a single symbol."""
    print(f"\n🧪 Testing live trading simulation for {TEST_SYMBOL}")
    print("=" * 60)
    
    # Initialize MT5
    if mt5 and not initialize_mt5():
        print("❌ Failed to initialize MT5")
        return
    
    mt5_timeframe = TIMEFRAMES.get(TIMEFRAME)
    lookback = require_analysis_params(TIMEFRAME).lookback
    
    print(f"  Timeframe: {TIMEFRAME}")
    print(f"  Lookback: {lookback} bars")
    print(f"  MT5 TF: {mt5_timeframe}")
    
    # Create failure context
    ctx = _FailureContext(TEST_SYMBOL)
    
    print(f"\n🔍 Processing {TEST_SYMBOL}...")
    
    try:
        _process_symbol(
            symbol=TEST_SYMBOL,
            timeframe=TIMEFRAME,
            mt5_timeframe=mt5_timeframe,
            lookback=lookback,
            trend_alignment_timeframes=TREND_ALIGNMENT_TFS,
            ctx=ctx,
        )
    finally:
        # Store failure if one occurred
        ctx.store_if_failed()
    
    # Report results
    if ctx.has_failed():
        print(f"\n❌ Signal detection FAILED:")
        print(f"   Gate: {ctx.failed_gate}")
        print(f"   Reason: {ctx.fail_reason}")
        print(f"   Ref Price: {ctx.reference_price}")
    else:
        print(f"\n✅ Signal detection completed (may have found a signal or been blocked)")
    
    # Check database tables
    print("\n" + "=" * 60)
    check_failed_signals_table()
    check_entry_signals_table()


if __name__ == "__main__":
    run_test()
