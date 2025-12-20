"""Entry point for running the offline replay engine.

Run from data-retriever directory:
    python replay_runner.py
    python replay_runner.py --symbols EURUSD --start 2025-11-01T00:00:00 --end 2025-11-05T23:00:00
"""

import argparse
from datetime import datetime

from replay.config import REPLAY_SYMBOLS, REPLAY_START_DATE, REPLAY_END_DATE
from replay.runner import run_replay


def run():
    """CLI entrypoint for running replay."""
    parser = argparse.ArgumentParser(
        description="Run offline replay engine for trading signal simulation"
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=None,
        help=f"Symbols to replay (default: {REPLAY_SYMBOLS})",
    )
    parser.add_argument(
        "--start",
        type=str,
        default=None,
        help=f"Start date ISO format (default: {REPLAY_START_DATE.isoformat()})",
    )
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help=f"End date ISO format (default: {REPLAY_END_DATE.isoformat()})",
    )
    
    args = parser.parse_args()
    
    # Parse dates if provided
    start_date = None
    end_date = None
    if args.start:
        start_date = datetime.fromisoformat(args.start)
    if args.end:
        end_date = datetime.fromisoformat(args.end)
    
    # Run replay
    stats = run_replay(
        symbols=args.symbols,
        start_date=start_date,
        end_date=end_date,
    )
    
    # Exit with error code if any errors occurred
    exit(1 if stats.errors > 0 else 0)
