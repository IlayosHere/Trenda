"""Historical signal verification test - Validates production matches replay.

Tests that production signal detection finds the same signals as replay
with the specific AOIs and parameters from the database.

Usage:
    python test_single_symbol.py
"""

from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from typing import Optional, Dict, List

import MetaTrader5 as mt5
import pandas as pd
import numpy as np

# =============================================================================
# Configuration - Signals from Replay DB to Validate
# =============================================================================
TEST_SYMBOL = "AUDJPY"

# Known signals from replay DB - Now with CORRECTED timezone (after broker offset fix)
# Testing signal at 10 UTC and also 9 UTC to see why it didn't fire earlier
DB_SIGNALS = [
    # Test 9 UTC to see why no signal (1 hour before actual signal)
    {
        "signal_time": "2025-11-26 00:00:00+02",  # = 09:00 UTC (1 hour before actual)
        "aoi_low": 100.508,
        "aoi_high": 100.87,
        "aoi_timeframe": "1D",
        "atr_1h": 0.18685204081632728,
    },
    # Actual signal at 10 UTC
    {
        "signal_time": "2025-11-19 08:00:00+02",  # = 10:00 UTC
        "aoi_low": 100.555,
        "aoi_high": 100.833,
        "aoi_timeframe": "4H",
        "atr_1h": 0.19982653061224553,
    },
]






# Lookback sizes
LOOKBACK_1H = 200
LOOKBACK_4H = 200
LOOKBACK_1D = 140
LOOKBACK_1W = 52


# =============================================================================
# Helper Functions
# =============================================================================
def print_section(title: str):
    """Print a section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def init_mt5():
    """Initialize MT5."""
    if not mt5.initialize():
        print("❌ MT5 initialization failed")
        return False
    print("✅ MT5 initialized")
    return True


def parse_signal_time(time_str: str) -> datetime:
    """Parse signal time string to UTC datetime."""
    dt = datetime.fromisoformat(time_str)
    return dt.astimezone(timezone.utc)


def fetch_candles_at_time(symbol: str, timeframe: int, end_time: datetime, count: int, debug: bool = False) -> pd.DataFrame:
    """Fetch candles up to and including the signal candle.
    
    IMPORTANT: signal_time (end_time) IS the MT5 candle start time we want to include.
    We enter the trade at the CLOSE of this candle (signal_time + 1 hour for 1H).
    
    MT5's copy_rates_range is EXCLUSIVE of end_time, so we add buffer to include it.
    MT5 timestamps are in BROKER LOCAL TIME (EET, UTC+2) - we correct for this.
    """
    from configuration.broker_config import MT5_BROKER_UTC_OFFSET
    
    end_time_naive = end_time.replace(tzinfo=None)
    # Add 2 hours buffer to ensure signal candle is included (MT5 is exclusive of end_time)
    # Also add broker offset since MT5 times are in broker local time
    fetch_end = end_time_naive + timedelta(hours=2 + MT5_BROKER_UTC_OFFSET)
    start_time = end_time_naive - timedelta(days=count * 7) + timedelta(hours=MT5_BROKER_UTC_OFFSET)
    
    if debug:
        print(f"\n  [DEBUG fetch_candles] symbol={symbol}, tf={timeframe}")
        print(f"  [DEBUG fetch_candles] signal_time (candle we want)={end_time}")
        print(f"  [DEBUG fetch_candles] MT5 fetch range: {start_time} to {fetch_end} (exclusive)")
        print(f"  [DEBUG fetch_candles] Broker offset: {MT5_BROKER_UTC_OFFSET}h")
    
    rates = mt5.copy_rates_range(symbol, timeframe, start_time, fetch_end)
    if rates is None or len(rates) == 0:
        if debug:
            print(f"  [DEBUG fetch_candles] No rates returned from MT5!")
        return pd.DataFrame()
    
    df = pd.DataFrame(rates)
    
    # Apply broker offset correction (MT5 times are in broker local time, not UTC)
    broker_offset_seconds = MT5_BROKER_UTC_OFFSET * 3600
    df["time"] = pd.to_datetime(df["time"] - broker_offset_seconds, unit="s", utc=True)
    
    if debug:
        print(f"  [DEBUG fetch_candles] MT5 returned {len(df)} candles (after offset correction)")
        print(f"  [DEBUG fetch_candles] MT5 last 5 times: {df['time'].tail(5).tolist()}")
    
    # Include candles up to and including signal_time
    df = df[df["time"] <= end_time].tail(count)
    
    if debug:
        print(f"  [DEBUG fetch_candles] After filter (<={end_time}): {len(df)} candles")
        if len(df) > 0:
            last_candle = df.iloc[-1]
            print(f"  [DEBUG fetch_candles] Last candle: {last_candle['time']} | Close={last_candle['close']:.5f}")
            expected = end_time
            if last_candle['time'] != expected:
                print(f"  [DEBUG fetch_candles] ⚠️ WARNING: Expected {expected} but got {last_candle['time']}")
    
    return df





# =============================================================================
# Test Functions
# =============================================================================
def test_trend_at_time(symbol: str, signal_time: datetime):
    """Test trend detection using ACTUAL SYSTEM CODE."""
    print_section("1. TREND DETECTION (System Code)")
    
    from trend.structure import analyze_snake_trend, get_swing_points
    from configuration import require_analysis_params
    
    trends = {}
    
    for tf_label, tf_mt5, lookback in [
        ("4H", mt5.TIMEFRAME_H4, LOOKBACK_4H),
        ("1D", mt5.TIMEFRAME_D1, LOOKBACK_1D),
        ("1W", mt5.TIMEFRAME_W1, LOOKBACK_1W),
    ]:
        candles = fetch_candles_at_time(symbol, tf_mt5, signal_time, lookback)
        if candles.empty:
            print(f"  ❌ {tf_label}: No candles")
            continue
        
        prices = candles["close"].values
        
        try:
            params = require_analysis_params(tf_label)
            distance = params.distance
            prominence = params.prominence
        except Exception:
            distance = 1
            prominence = 0.0004
        
        try:
            swings = get_swing_points(prices, distance, prominence)
            result = analyze_snake_trend(swings)
            
            if result:
                trends[tf_label] = result.trend.value if result.trend else "neutral"
                print(f"  {tf_label}: {trends[tf_label].upper()}")
            else:
                trends[tf_label] = "neutral"
                print(f"  {tf_label}: NEUTRAL")
        except Exception as e:
            print(f"  ❌ {tf_label}: Error - {e}")
            trends[tf_label] = "neutral"
    
    return trends


def test_aoi_detection(symbol: str, signal_time: datetime, direction: str, expected_aoi: dict):
    """Test if production AOI detection finds the expected AOI zone."""
    print_section(f"2. AOI DETECTION ({expected_aoi['aoi_timeframe']})")
    
    from models import TrendDirection
    from aoi.context import build_context, extract_swings
    from aoi.pipeline import generate_aoi_zones
    from aoi.scoring import apply_directional_weighting_and_classify
    from aoi.analyzer import filter_noisy_points
    from aoi.aoi_configuration import AOI_CONFIGS
    from utils.indicators import calculate_atr
    from utils.forex import price_to_pips, get_pip_size
    
    trend_dir = TrendDirection.BULLISH if direction == "bullish" else TrendDirection.BEARISH
    pip_size = get_pip_size(symbol)
    
    tf_label = expected_aoi["aoi_timeframe"]
    expected_low = expected_aoi["aoi_low"]
    expected_high = expected_aoi["aoi_high"]
    
    # Fetch candles for the expected timeframe
    if tf_label == "4H":
        tf_mt5 = mt5.TIMEFRAME_H4
        lookback = 180
    else:  # 1D
        tf_mt5 = mt5.TIMEFRAME_D1
        lookback = 140
    
    candles = fetch_candles_at_time(symbol, tf_mt5, signal_time, lookback)
    
    if candles.empty:
        print(f"  ❌ No {tf_label} candles for AOI")
        return False, []
    
    print(f"  {tf_label} candles: {len(candles)} (last: {candles.iloc[-1]['time']})")
    
    # Get AOI settings
    settings = AOI_CONFIGS.get(tf_label)
    if settings is None:
        print(f"  ❌ No AOI settings for {tf_label}")
        return False, []
    
    # Calculate ATR
    atr_price = calculate_atr(candles)
    atr_pips = price_to_pips(atr_price, pip_size)
    print(f"  ATR {tf_label}: {atr_price:.5f} ({atr_pips:.1f} pips)")
    
    # Build context
    context = build_context(settings, symbol, atr_pips)
    if context is None:
        print(f"  ❌ Failed to build AOI context")
        return False, []
    
    # Extract swings and generate zones
    prices = np.asarray(candles["close"].values)
    swings = extract_swings(prices, context)
    print(f"  Raw swings: {len(swings)}")
    
    important_swings = filter_noisy_points(swings)
    print(f"  Important swings: {len(important_swings)}")
    
    last_bar_idx = len(prices) - 1
    zones = generate_aoi_zones(important_swings, last_bar_idx, context)
    print(f"  Zones generated: {len(zones)}")
    
    # Apply scoring
    current_price = float(prices[-1])
    zones_scored = apply_directional_weighting_and_classify(
        zones, current_price, trend_dir, context
    )
    
    tradable_zones = [z for z in zones_scored if z.classification == "tradable"]
    print(f"  Tradable zones: {len(tradable_zones)}")
    
    # Check if expected AOI is found
    found_match = False
    matching_zone = None
    
    print(f"\n  Expected AOI: {expected_low:.5f} - {expected_high:.5f}")
    print(f"  Matching: Exact (5 decimal places)")
    
    for i, zone in enumerate(tradable_zones):
        # Exact match at 5 decimal places
        low_match = round(zone.lower, 5) == round(expected_low, 5)
        high_match = round(zone.upper, 5) == round(expected_high, 5)
        
        if low_match and high_match:
            found_match = True
            matching_zone = zone
            print(f"\n  ✅ MATCH FOUND: Zone {i+1}")
            print(f"     Production: {zone.lower:.5f} - {zone.upper:.5f}")
            print(f"     Database:   {expected_low:.5f} - {expected_high:.5f}")
        else:
            print(f"  Zone {i+1}: {zone.lower:.5f} - {zone.upper:.5f}")
    
    if not found_match:
        print(f"\n  ❌ EXPECTED AOI NOT FOUND IN PRODUCTION")
        print(f"     Expected: {expected_low:.5f} - {expected_high:.5f}")
    
    return found_match, tradable_zones


def compute_htf_context_historical(symbol: str, signal_time: datetime, entry_price: float, atr_1h: float, direction: str):
    """Compute HTF context from HISTORICAL candles at signal time (like replay).
    
    This matches what replay does - fetches candles ending at signal_time.
    """
    from models import TrendDirection
    from entry.gates.config import NO_OBSTACLE_DISTANCE_ATR
    from dataclasses import dataclass
    from typing import Optional, Dict
    
    @dataclass
    class HTFContextHistorical:
        htf_range_position_daily: Optional[float] = None
        htf_range_position_weekly: Optional[float] = None
        distance_to_next_htf_obstacle_atr: Optional[float] = None
        h4_high: Optional[float] = None
        h4_low: Optional[float] = None
        daily_high: Optional[float] = None
        daily_low: Optional[float] = None
        weekly_high: Optional[float] = None
        weekly_low: Optional[float] = None
    
    is_bullish = direction == "bullish"
    
    # Fetch HISTORICAL candles ending at signal time (like replay does)
    candles_4h = fetch_candles_at_time(symbol, mt5.TIMEFRAME_H4, signal_time, 10)
    candles_1d = fetch_candles_at_time(symbol, mt5.TIMEFRAME_D1, signal_time, 10)
    candles_1w = fetch_candles_at_time(symbol, mt5.TIMEFRAME_W1, signal_time, 10)
    
    # Get last candle high/low for each timeframe
    h4_high = float(candles_4h.iloc[-1]["high"]) if not candles_4h.empty else None
    h4_low = float(candles_4h.iloc[-1]["low"]) if not candles_4h.empty else None
    daily_high = float(candles_1d.iloc[-1]["high"]) if not candles_1d.empty else None
    daily_low = float(candles_1d.iloc[-1]["low"]) if not candles_1d.empty else None
    weekly_high = float(candles_1w.iloc[-1]["high"]) if not candles_1w.empty else None
    weekly_low = float(candles_1w.iloc[-1]["low"]) if not candles_1w.empty else None
    
    # Compute daily range position
    daily_pos = None
    if daily_high is not None and daily_low is not None:
        daily_range = daily_high - daily_low
        if daily_range > 0:
            daily_pos = (entry_price - daily_low) / daily_range
            # Don't clamp - show actual position even if outside range
    
    # Compute weekly range position
    weekly_pos = None
    if weekly_high is not None and weekly_low is not None:
        weekly_range = weekly_high - weekly_low
        if weekly_range > 0:
            weekly_pos = (entry_price - weekly_low) / weekly_range
    
    # Compute obstacle distance
    obstacles = []
    if is_bullish:
        if h4_high is not None and h4_high > entry_price:
            obstacles.append((h4_high - entry_price) / atr_1h)
        if daily_high is not None and daily_high > entry_price:
            obstacles.append((daily_high - entry_price) / atr_1h)
        if weekly_high is not None and weekly_high > entry_price:
            obstacles.append((weekly_high - entry_price) / atr_1h)
    else:
        if h4_low is not None and h4_low < entry_price:
            obstacles.append((entry_price - h4_low) / atr_1h)
        if daily_low is not None and daily_low < entry_price:
            obstacles.append((entry_price - daily_low) / atr_1h)
        if weekly_low is not None and weekly_low < entry_price:
            obstacles.append((entry_price - weekly_low) / atr_1h)
    
    obstacle_dist = NO_OBSTACLE_DISTANCE_ATR if not obstacles else min(obstacles)
    
    return HTFContextHistorical(
        htf_range_position_daily=daily_pos,
        htf_range_position_weekly=weekly_pos,
        distance_to_next_htf_obstacle_atr=obstacle_dist,
        h4_high=h4_high,
        h4_low=h4_low,
        daily_high=daily_high,
        daily_low=daily_low,
        weekly_high=weekly_high,
        weekly_low=weekly_low,
    )


def test_gates_and_pattern(symbol: str, signal_time: datetime, direction: str, expected_aoi: dict, trends: dict):
    """Test gate checks using HISTORICAL HTF context (like replay)."""
    print_section("3. GATE CHECKS (Historical HTF Context)")
    
    from entry.gates import check_all_gates
    from entry.htf_context import get_conflicted_timeframe
    from models import TrendDirection
    from utils.indicators import calculate_atr
    
    trend_dir = TrendDirection.BULLISH if direction == "bullish" else TrendDirection.BEARISH
    
    candles_1h = fetch_candles_at_time(symbol, mt5.TIMEFRAME_H1, signal_time, LOOKBACK_1H)
    if candles_1h.empty:
        print("  ❌ No 1H candles")
        return None, None
    
    entry_price = float(candles_1h.iloc[-1]["close"])
    atr_1h = calculate_atr(candles_1h)
    
    print(f"  Signal Time (UTC): {signal_time.strftime('%Y-%m-%d %H:%M')}")
    print(f"  Entry Price (close): {entry_price:.5f}")
    print(f"  ATR 1H (calculated): {atr_1h:.10f}")
    print(f"  ATR 1H (from DB):    {expected_aoi['atr_1h']:.10f}")
    print(f"  ATR difference:      {abs(atr_1h - expected_aoi['atr_1h']):.10f}")
    
    # Compute HTF context from HISTORICAL candles (like replay does)
    htf_context = compute_htf_context_historical(
        symbol,
        signal_time,
        entry_price,
        atr_1h,
        direction,
    )
    
    print(f"\n  HTF Context (from HISTORICAL candles at signal time):")
    print(f"    Daily Range Position: {htf_context.htf_range_position_daily:.4f}" if htf_context.htf_range_position_daily is not None else "    Daily Range Position: N/A")
    print(f"    Weekly Range Position: {htf_context.htf_range_position_weekly:.4f}" if htf_context.htf_range_position_weekly is not None else "    Weekly Range Position: N/A")
    print(f"    Next Obstacle Distance: {htf_context.distance_to_next_htf_obstacle_atr:.2f} ATR" if htf_context.distance_to_next_htf_obstacle_atr is not None else "    Next Obstacle Distance: N/A")
    
    # Print levels for debugging
    print(f"\n  Last Candle High/Low (HISTORICAL at signal time):")
    print(f"    4H: High={htf_context.h4_high:.5f}, Low={htf_context.h4_low:.5f}" if htf_context.h4_high else "    4H: N/A")
    print(f"    1D: High={htf_context.daily_high:.5f}, Low={htf_context.daily_low:.5f}" if htf_context.daily_high else "    1D: N/A")
    print(f"    1W: High={htf_context.weekly_high:.5f}, Low={htf_context.weekly_low:.5f}" if htf_context.weekly_high else "    1W: N/A")
    
    # Get conflicted timeframe
    conflicted_tf = get_conflicted_timeframe(
        trends.get("4H"),
        trends.get("1D"),
        trends.get("1W"),
        trend_dir,
    )
    
    print(f"\n  Conflicted TF: {conflicted_tf or 'None (all aligned)'}")
    
    # Check gates
    gate_result = check_all_gates(
        signal_time=signal_time,
        symbol=symbol,
        direction=trend_dir,
        conflicted_tf=conflicted_tf,
        htf_range_position_daily=htf_context.htf_range_position_daily,
        htf_range_position_weekly=htf_context.htf_range_position_weekly,
        distance_to_next_htf_obstacle_atr=htf_context.distance_to_next_htf_obstacle_atr,
    )
    
    print(f"\n  Gate Results:")
    print(f"    Overall Passed: {gate_result.passed}")
    
    if not gate_result.passed:
        print(f"    ❌ Failed Gate: {gate_result.failed_gate}")
        print(f"    ❌ Reason: {gate_result.failed_reason}")
    else:
        print("    ✅ All gates passed")
    
    return gate_result, atr_1h


def test_pattern_for_aoi(symbol: str, signal_time: datetime, direction: str, expected_aoi: dict):
    """Test pattern finding with detailed debugging."""
    print_section("4. PATTERN FINDING (Detailed Debug)")
    
    from entry.pattern_finder import find_entry_pattern
    from models import TrendDirection
    from dataclasses import dataclass
    
    trend_dir = TrendDirection.BULLISH if direction == "bullish" else TrendDirection.BEARISH
    
    candles_1h = fetch_candles_at_time(symbol, mt5.TIMEFRAME_H1, signal_time, LOOKBACK_1H, debug=True)

    if candles_1h.empty:
        print("  ❌ No 1H candles")
        return None
    
    print(f"  1H candles fetched: {len(candles_1h)}")
    print(f"  First candle time: {candles_1h.iloc[0]['time']}")
    print(f"  Last candle time:  {candles_1h.iloc[-1]['time']}")
    
    # Create a mock AOI object with the expected bounds
    @dataclass
    class MockAOI:
        lower: float
        upper: float
        classification: str = "tradable"
    
    mock_aoi = MockAOI(lower=expected_aoi["aoi_low"], upper=expected_aoi["aoi_high"])
    aoi_low = mock_aoi.lower
    aoi_high = mock_aoi.upper
    
    print(f"\n  Testing pattern in AOI: {aoi_low:.5f} - {aoi_high:.5f}")
    print(f"  Direction: {direction}")
    
    # Check recent candles interaction with AOI
    print(f"\n  === Last 20 candles vs AOI ===")
    last_20 = candles_1h.tail(20)
    for idx, row in last_20.iterrows():
        t = row['time']
        o = row['open']
        h = row['high']
        l = row['low']
        c = row['close']
        
        # Check if candle touches AOI
        touches_aoi = l <= aoi_high and h >= aoi_low
        inside_aoi = l >= aoi_low and h <= aoi_high
        close_in_aoi = aoi_low <= c <= aoi_high
        
        marker = ""
        if close_in_aoi:
            marker = " ← CLOSE IN AOI"
        elif touches_aoi:
            marker = " ← touches"
        
        print(f"    {t}: O={o:.5f} H={h:.5f} L={l:.5f} C={c:.5f}{marker}")
    
    # Find pattern
    print(f"\n  Calling find_entry_pattern...")
    pattern = find_entry_pattern(candles_1h, mock_aoi, trend_dir)
    
    if pattern:
        pattern_time = pattern.candles[-1].time
        pattern_price = pattern.candles[-1].close
        
        print(f"\n  ✅ Pattern found!")
        print(f"     Direction: {pattern.direction.value}")
        print(f"     Candles in pattern: {len(pattern.candles)}")
        print(f"     Signal Time: {pattern_time}")
        print(f"     Entry Price: {pattern_price:.5f}")
        print(f"\n     Pattern candles:")
        for i, pc in enumerate(pattern.candles):
            print(f"       {i+1}. {pc.time}: O={pc.open:.5f} H={pc.high:.5f} L={pc.low:.5f} C={pc.close:.5f}")
    else:
        print(f"\n  ❌ No pattern found in expected AOI")
        print(f"\n  Possible reasons:")
        print(f"    - Price didn't interact with AOI in the pattern window")
        print(f"    - Pattern criteria not met (touch+departure for bullish)")
        print(f"    - Candle times don't align with signal time")
    
    return pattern


def test_live_execution(symbol: str, signal_time: datetime, direction: str, aoi: dict, atr_1h: float):
    """Test live execution data - simulate execution 1 minute after signal candle closes.
    
    Uses HISTORICAL price data to simulate what would happen at signal_time + 1hour + 1minute.
    Entry price = open of the candle that starts at signal_time + 1hour (i.e., the next candle after signal).
    """
    print_section("5. LIVE EXECUTION TEST (1 minute after close)")
    
    from entry.live_execution import get_account_balance, get_symbol_info
    from entry.gates.config import SL_BUFFER_ATR, RR_MULTIPLE
    from models import TrendDirection
    
    trend_dir = TrendDirection.BULLISH if direction == "bullish" else TrendDirection.BEARISH
    
    # Execution time = signal_time + 1 hour + 1 minute (1 min after candle close)
    execution_time = signal_time + timedelta(hours=1, minutes=1)
    print(f"  Signal Candle Time: {signal_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"  Simulated Execution Time: {execution_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"  (1 minute after signal candle closes)")
    print()
    
    # Fetch the candle that contains execution_time
    # For execution at 13:01, we want the candle that starts at 13:00 (its open price)
    next_candle_start = signal_time + timedelta(hours=1)
    
    # Fetch a few candles around that time
    candles = fetch_candles_at_time(symbol, mt5.TIMEFRAME_H1, next_candle_start + timedelta(hours=1), 5)
    
    if candles.empty:
        print("  ❌ Could not fetch historical candles for execution time")
        return None
    
    # Find the candle that starts at next_candle_start
    execution_candle = candles[candles["time"] == next_candle_start]
    
    if execution_candle.empty:
        print(f"  ❌ No candle found at {next_candle_start}")
        print(f"  Available candles: {candles['time'].tolist()}")
        return None
    
    # Entry price = open of the next candle (simulates entering at 13:01 for a 12:00 signal)
    entry_price = float(execution_candle.iloc[0]["open"])
    candle_high = float(execution_candle.iloc[0]["high"])
    candle_low = float(execution_candle.iloc[0]["low"])
    candle_close = float(execution_candle.iloc[0]["close"])
    
    print(f"  === HISTORICAL ENTRY DATA ===")
    print(f"  Entry Candle: {next_candle_start.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  Entry Price (candle open): {entry_price:.5f}")
    print(f"  Candle H/L/C: {candle_high:.5f}/{candle_low:.5f}/{candle_close:.5f}")
    print()
    
    # Show inputs
    print(f"  === INPUTS ===")
    print(f"  Symbol:     {symbol}")
    print(f"  Direction:  {direction}")
    print(f"  AOI:        {aoi['aoi_low']:.5f} - {aoi['aoi_high']:.5f}")
    print(f"  ATR 1H:     {atr_1h:.7f}")
    print()
    
    # Get account info (current - can't get historical)
    balance = get_account_balance()
    if balance:
        print(f"  Account Balance (current): ${balance:.2f}")
    
    symbol_info = get_symbol_info(symbol)
    if symbol_info:
        print(f"  Symbol Point: {symbol_info['point']}")
        print(f"  Volume Min/Max/Step: {symbol_info['volume_min']}/{symbol_info['volume_max']}/{symbol_info['volume_step']}")
    print()
    
    # Calculate SL/TP using the same logic as production
    print(f"  === SL/TP CALCULATIONS ===")
    print(f"  SL Buffer (config): {SL_BUFFER_ATR} ATR")
    print(f"  R:R Multiple (config): {RR_MULTIPLE}")
    print()
    
    # Calculate SL distance using SL_AOI_FAR_PLUS_0_25 model
    if direction == "bullish":
        far_edge = aoi["aoi_low"]
        far_edge_distance = entry_price - far_edge
        print(f"  Far Edge (AOI low for bullish): {far_edge:.5f}")
    else:
        far_edge = aoi["aoi_high"]
        far_edge_distance = far_edge - entry_price
        print(f"  Far Edge (AOI high for bearish): {far_edge:.5f}")
    
    print(f"  Distance to Far Edge: {far_edge_distance:.5f} ({far_edge_distance / atr_1h:.3f} ATR)")
    
    # SL in ATR units
    sl_distance_atr = (far_edge_distance / atr_1h) + SL_BUFFER_ATR
    tp_distance_atr = sl_distance_atr * RR_MULTIPLE
    
    # Convert to price distance
    sl_distance_price = sl_distance_atr * atr_1h
    tp_distance_price = tp_distance_atr * atr_1h
    
    # Calculate SL/TP prices
    if direction == "bullish":
        sl_price = entry_price - sl_distance_price
        tp_price = entry_price + tp_distance_price
    else:
        sl_price = entry_price + sl_distance_price
        tp_price = entry_price - tp_distance_price
    
    # Calculate pip distances
    if symbol_info:
        point = symbol_info["point"]
        digits = symbol_info.get("digits", 5)
        pip_size = point * 10 if digits in (3, 5) else point
        sl_distance_pips = sl_distance_price / pip_size
        tp_distance_pips = tp_distance_price / pip_size
    else:
        sl_distance_pips = 0.0
        tp_distance_pips = 0.0
    
    print(f"  SL Distance: {sl_distance_atr:.3f} ATR = {sl_distance_pips:.1f} pips")
    print(f"  TP Distance: {tp_distance_atr:.3f} ATR = {tp_distance_pips:.1f} pips")
    print()
    
    print(f"  === EXECUTION DATA ===")
    print(f"  Entry Price: {entry_price:.5f}")
    print(f"  Stop Loss:   {sl_price:.5f}")
    print(f"  Take Profit: {tp_price:.5f}")
    print()
    
    # Visual representation
    if direction == "bullish":
        print(f"  === VISUAL (Bullish) ===")
        print(f"       TP:     {tp_price:.5f}  ↑ (+{tp_distance_pips:.1f} pips)")
        print(f"       Entry:  {entry_price:.5f}  ←")
        print(f"       AOI:    {aoi['aoi_high']:.5f}")
        print(f"       AOI:    {aoi['aoi_low']:.5f}")
        print(f"       SL:     {sl_price:.5f}  ↓ (-{sl_distance_pips:.1f} pips)")
    else:
        print(f"  === VISUAL (Bearish) ===")
        print(f"       SL:     {sl_price:.5f}  ↑ (+{sl_distance_pips:.1f} pips)")
        print(f"       AOI:    {aoi['aoi_high']:.5f}")
        print(f"       AOI:    {aoi['aoi_low']:.5f}")
        print(f"       Entry:  {entry_price:.5f}  ←")
        print(f"       TP:     {tp_price:.5f}  ↓ (-{tp_distance_pips:.1f} pips)")
    
    return {
        "entry_price": entry_price,
        "sl_price": sl_price,
        "tp_price": tp_price,
        "sl_distance_atr": sl_distance_atr,
        "tp_distance_atr": tp_distance_atr,
    }


def test_signal(signal_config: dict):

    """Run complete test for one signal."""
    signal_time = parse_signal_time(signal_config["signal_time"])
    
    print("\n")
    print("╔" + "═" * 68 + "╗")
    print(f"║  VALIDATING SIGNAL: {TEST_SYMBOL} @ {signal_time.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"║  Expected AOI ({signal_config['aoi_timeframe']}): {signal_config['aoi_low']:.5f} - {signal_config['aoi_high']:.5f}")
    print("╚" + "═" * 68 + "╝")
    
    # 1. Trend detection
    trends = test_trend_at_time(TEST_SYMBOL, signal_time)
    
    if not trends:
        print("\n❌ No trend data - stopping")
        return {"signal": signal_config, "aoi_found": False, "gates_passed": False, "pattern_found": False}
    
    direction = trends.get("1D", trends.get("4H", "neutral"))
    print(f"\n  → Using direction: {direction}")
    
    if direction == "neutral":
        direction = trends.get("4H", "bullish")
        print(f"  → Fallback to 4H: {direction}")
    
    # 2. AOI detection - check if we find the expected AOI
    aoi_found, all_aois = test_aoi_detection(TEST_SYMBOL, signal_time, direction, signal_config)
    
    # 3. Gate checks with production HTF context
    gate_result, atr_1h = test_gates_and_pattern(TEST_SYMBOL, signal_time, direction, signal_config, trends)
    
    # 4. Pattern finding for expected AOI
    pattern = test_pattern_for_aoi(TEST_SYMBOL, signal_time, direction, signal_config)
    
    # 5. Live execution test (if pattern found)
    if pattern and gate_result and gate_result.passed:
        exec_data = test_live_execution(TEST_SYMBOL, signal_time, direction, signal_config, atr_1h)
    
    # Summary
    print_section("SIGNAL VALIDATION SUMMARY")
    print(f"  AOI Found:      {'✅ YES' if aoi_found else '❌ NO'}")
    print(f"  Gates Passed:   {'✅ YES' if gate_result and gate_result.passed else '❌ NO'}")
    print(f"  Pattern Found:  {'✅ YES' if pattern else '❌ NO'}")
    
    return {
        "signal": signal_config,
        "aoi_found": aoi_found,
        "gates_passed": gate_result.passed if gate_result else False,
        "pattern_found": pattern is not None,
    }



def main():
    """Run validation for all DB signals."""
    print("\n" + "=" * 70)
    print(f"  PRODUCTION VS REPLAY SIGNAL VALIDATION: {TEST_SYMBOL}")
    print("  Verifying production finds the same signals as replay DB")
    print("=" * 70)
    print(f"  Testing {len(DB_SIGNALS)} signals from database")
    
    if not init_mt5():
        return
    
    results = []
    
    try:
        for signal_config in DB_SIGNALS:
            result = test_signal(signal_config)
            results.append(result)
        
        # Final summary
        print_section("FINAL VALIDATION RESULTS")
        
        total = len(results)
        aoi_matches = sum(1 for r in results if r["aoi_found"])
        gate_passes = sum(1 for r in results if r["gates_passed"])
        pattern_matches = sum(1 for r in results if r["pattern_found"])
        
        print(f"  Total Signals Tested: {total}")
        print(f"  AOI Matches:          {aoi_matches}/{total}")
        print(f"  Gates Passed:         {gate_passes}/{total}")
        print(f"  Patterns Found:       {pattern_matches}/{total}")
        
        if aoi_matches == total and gate_passes == total and pattern_matches == total:
            print("\n  ✅ PRODUCTION FULLY MATCHES REPLAY!")
        else:
            print("\n  ⚠️ DIFFERENCES DETECTED - Review above output")
        
    finally:
        mt5.shutdown()
        print("\n✅ MT5 shutdown")


if __name__ == "__main__":
    main()
