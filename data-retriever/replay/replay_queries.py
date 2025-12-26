"""SQL queries for replay schema operations.

All queries target the trenda_replay schema instead of trenda.
Mirrors production queries from database/queries.py.
"""

from .config import SCHEMA_NAME, SL_MODEL_VERSION, TP_MODEL_VERSION

# Import TP_R_MULTIPLIER from sl_calculator
from entry.sl_calculator import TP_R_MULTIPLIER

# =============================================================================
# Entry Signal Queries
# =============================================================================

CHECK_SIGNAL_EXISTS = f"""
    SELECT EXISTS(
        SELECT 1 FROM {SCHEMA_NAME}.entry_signal
        WHERE symbol = %s AND signal_time = %s AND sl_model_version = %s AND tp_model_version = %s
    )
"""

GET_SIGNAL_ID = f"""
    SELECT id FROM {SCHEMA_NAME}.entry_signal
    WHERE symbol = %s AND signal_time = %s AND sl_model_version = %s AND tp_model_version = %s
"""

# Find trade_id from a signal 1 hour earlier (for grouping break + after-break signals)
GET_RELATED_SIGNAL_TRADE_ID = f"""
    SELECT trade_id FROM {SCHEMA_NAME}.entry_signal
    WHERE symbol = %s 
    AND signal_time = %s - INTERVAL '1 hour'
    AND trade_id IS NOT NULL
    LIMIT 1
"""

INSERT_REPLAY_ENTRY_SIGNAL = f"""
    INSERT INTO {SCHEMA_NAME}.entry_signal (
        symbol, signal_time, direction,
        trend_4h, trend_1d, trend_1w, trend_alignment_strength,
        aoi_timeframe, aoi_low, aoi_high, aoi_classification,
        entry_price, atr_1h,
        final_score, tier,
        is_break_candle_last,
        sl_model_version, tp_model_version,
        aoi_structural_sl_distance_price, aoi_structural_sl_distance_atr,
        effective_sl_distance_price, effective_sl_distance_atr,
        effective_tp_distance_atr, effective_tp_distance_price,
        trade_profile,
        conflicted_tf,
        max_retest_penetration_atr, bars_between_retest_and_break,
        hour_of_day_utc, session_bucket,
        aoi_touch_count_since_creation,
        trade_id
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    RETURNING id
"""

INSERT_REPLAY_ENTRY_SIGNAL_SCORE = f"""
    INSERT INTO {SCHEMA_NAME}.entry_signal_score (
        entry_signal_id, stage_name, raw_score, weight, weighted_score
    )
    VALUES (%s, %s, %s, %s, %s)
"""

# =============================================================================
# Signal Outcome Queries
# =============================================================================

# Note: effective_tp_distance_price is computed dynamically in Python (SL × 2.25)
# Only fetch signals matching current model versions
FETCH_PENDING_REPLAY_SIGNALS = f"""
    SELECT id, symbol, signal_time, direction, entry_price, atr_1h,
           aoi_low, aoi_high, effective_sl_distance_price
    FROM {SCHEMA_NAME}.entry_signal
    WHERE outcome_computed = FALSE
      AND sl_model_version = '{SL_MODEL_VERSION}'
      AND tp_model_version = '{TP_MODEL_VERSION}'
    ORDER BY signal_time ASC
    LIMIT %s
"""

FETCH_SIGNAL_BY_ID = f"""
    SELECT id, symbol, signal_time, direction, entry_price, atr_1h,
           aoi_low, aoi_high, effective_sl_distance_price
    FROM {SCHEMA_NAME}.entry_signal
    WHERE id = %s
"""

INSERT_REPLAY_SIGNAL_OUTCOME = f"""
    INSERT INTO {SCHEMA_NAME}.signal_outcome (
        entry_signal_id, window_bars,
        mfe_atr, mae_atr,
        bars_to_mfe, bars_to_mae, first_extreme,
        realized_r, exit_reason, bars_to_exit,
        mfe_r, mae_r, bars_to_tp, bars_to_sl
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (entry_signal_id) DO NOTHING
    RETURNING id
"""

INSERT_REPLAY_CHECKPOINT_RETURN = f"""
    INSERT INTO {SCHEMA_NAME}.checkpoint_return (
        signal_outcome_id, bars_after, return_atr
    )
    VALUES (%s, %s, %s)
"""

MARK_REPLAY_OUTCOME_COMPUTED = f"""
    UPDATE {SCHEMA_NAME}.entry_signal
    SET outcome_computed = TRUE
    WHERE id = %s
"""

# =============================================================================
# Schema Creation (for initial setup)
# =============================================================================

CREATE_REPLAY_SCHEMA = f"""
    CREATE SCHEMA IF NOT EXISTS {SCHEMA_NAME}
"""

CREATE_REPLAY_ENTRY_SIGNAL_TABLE = f"""
    CREATE TABLE IF NOT EXISTS {SCHEMA_NAME}.entry_signal (
        id SERIAL PRIMARY KEY,
        symbol VARCHAR(20) NOT NULL,
        signal_time TIMESTAMPTZ NOT NULL,
        direction VARCHAR(10) NOT NULL,
        trend_4h VARCHAR(10),
        trend_1d VARCHAR(10),
        trend_1w VARCHAR(10),
        trend_alignment_strength INTEGER,
        aoi_timeframe VARCHAR(10),
        aoi_low NUMERIC,
        aoi_high NUMERIC,
        aoi_classification VARCHAR(20),
        entry_price NUMERIC,
        atr_1h NUMERIC,
        final_score NUMERIC,
        tier VARCHAR(20),
        is_break_candle_last BOOLEAN,
        sl_model_version TEXT NOT NULL,
        tp_model_version TEXT NOT NULL,
        aoi_structural_sl_distance_price NUMERIC,
        aoi_structural_sl_distance_atr NUMERIC,
        effective_sl_distance_price NUMERIC,
        effective_sl_distance_atr NUMERIC,
        effective_tp_distance_atr NUMERIC NOT NULL,
        effective_tp_distance_price NUMERIC NOT NULL,
        trade_profile TEXT,
        outcome_computed BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(symbol, signal_time)
    )
"""

CREATE_REPLAY_ENTRY_SIGNAL_SCORE_TABLE = f"""
    CREATE TABLE IF NOT EXISTS {SCHEMA_NAME}.entry_signal_score (
        id SERIAL PRIMARY KEY,
        entry_signal_id INTEGER REFERENCES {SCHEMA_NAME}.entry_signal(id) ON DELETE CASCADE,
        stage_name VARCHAR(10) NOT NULL,
        raw_score NUMERIC,
        weight NUMERIC,
        weighted_score NUMERIC
    )
"""

CREATE_REPLAY_SIGNAL_OUTCOME_TABLE = f"""
    CREATE TABLE IF NOT EXISTS {SCHEMA_NAME}.signal_outcome (
        id SERIAL PRIMARY KEY,
        entry_signal_id INTEGER UNIQUE REFERENCES {SCHEMA_NAME}.entry_signal(id) ON DELETE CASCADE,
        window_bars INTEGER,
        mfe_atr NUMERIC,
        mae_atr NUMERIC,
        bars_to_mfe INTEGER,
        bars_to_mae INTEGER,
        first_extreme VARCHAR(20),
        bars_to_aoi_sl_hit INTEGER,
        bars_to_r_1 INTEGER,
        bars_to_r_1_5 INTEGER,
        bars_to_r_2 INTEGER,
        aoi_rr_outcome VARCHAR(30),
        realized_r NUMERIC,
        exit_reason TEXT,
        bars_to_exit INTEGER,
        mfe_r NUMERIC,
        mae_r NUMERIC,
        bars_to_tp INTEGER,
        bars_to_sl INTEGER,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    )
"""

CREATE_REPLAY_CHECKPOINT_RETURN_TABLE = f"""
    CREATE TABLE IF NOT EXISTS {SCHEMA_NAME}.checkpoint_return (
        id SERIAL PRIMARY KEY,
        signal_outcome_id INTEGER REFERENCES {SCHEMA_NAME}.signal_outcome(id) ON DELETE CASCADE,
        bars_after INTEGER NOT NULL,
        return_atr NUMERIC NOT NULL,
        UNIQUE(signal_outcome_id, bars_after)
    )
"""

# =============================================================================
# Pre-Entry Context Queries
# =============================================================================

INSERT_REPLAY_PRE_ENTRY_CONTEXT = f"""
    INSERT INTO {SCHEMA_NAME}.pre_entry_context (
        entry_signal_id,
        lookback_bars, impulse_bars,
        pre_atr, pre_atr_ratio, pre_range_atr, pre_range_to_atr_ratio,
        pre_net_move_atr, pre_total_move_atr, pre_efficiency, pre_counter_bar_ratio,
        pre_aoi_touch_count, pre_bars_in_aoi, pre_last_touch_distance_atr,
        pre_impulse_net_atr, pre_impulse_efficiency, pre_large_bar_ratio,
        pre_overlap_ratio, pre_wick_ratio
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (entry_signal_id) DO NOTHING
"""

CREATE_REPLAY_PRE_ENTRY_CONTEXT_TABLE = f"""
    CREATE TABLE IF NOT EXISTS {SCHEMA_NAME}.pre_entry_context (
        entry_signal_id INTEGER PRIMARY KEY
            REFERENCES {SCHEMA_NAME}.entry_signal(id) ON DELETE CASCADE,
        lookback_bars INTEGER NOT NULL,
        impulse_bars INTEGER NOT NULL,
        pre_atr NUMERIC,
        pre_atr_ratio NUMERIC,
        pre_range_atr NUMERIC,
        pre_range_to_atr_ratio NUMERIC,
        pre_net_move_atr NUMERIC,
        pre_total_move_atr NUMERIC,
        pre_efficiency NUMERIC,
        pre_counter_bar_ratio NUMERIC,
        pre_aoi_touch_count INTEGER,
        pre_bars_in_aoi INTEGER,
        pre_last_touch_distance_atr NUMERIC,
        pre_impulse_net_atr NUMERIC,
        pre_impulse_efficiency NUMERIC,
        pre_large_bar_ratio NUMERIC,
        pre_overlap_ratio NUMERIC,
        pre_wick_ratio NUMERIC,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    )
"""

# =============================================================================
# Pre-Entry Context V2 Queries (Market Environment)
# =============================================================================

INSERT_REPLAY_PRE_ENTRY_CONTEXT_V2 = f"""
    INSERT INTO {SCHEMA_NAME}.pre_entry_context_v2 (
        entry_signal_id,
        htf_range_position_daily, htf_range_position_weekly,
        distance_to_daily_high_atr, distance_to_daily_low_atr,
        distance_to_weekly_high_atr, distance_to_weekly_low_atr,
        distance_to_4h_high_atr, distance_to_4h_low_atr,
        distance_to_next_htf_obstacle_atr,
        prev_session_high, prev_session_low,
        distance_to_prev_session_high_atr, distance_to_prev_session_low_atr,
        trend_age_bars_1h, trend_age_impulses,
        recent_trend_payoff_atr_24h, recent_trend_payoff_atr_48h,
        session_directional_bias,
        aoi_time_since_last_touch, aoi_last_reaction_strength,
        distance_from_last_impulse_atr,
        htf_range_size_daily_atr, htf_range_size_weekly_atr,
        aoi_midpoint_range_position_daily, aoi_midpoint_range_position_weekly
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (entry_signal_id) DO NOTHING
"""

CREATE_REPLAY_PRE_ENTRY_CONTEXT_V2_TABLE = f"""
    CREATE TABLE IF NOT EXISTS {SCHEMA_NAME}.pre_entry_context_v2 (
        entry_signal_id INTEGER PRIMARY KEY
            REFERENCES {SCHEMA_NAME}.entry_signal(id) ON DELETE CASCADE,
        htf_range_position_daily NUMERIC,
        htf_range_position_weekly NUMERIC,
        distance_to_daily_high_atr NUMERIC,
        distance_to_daily_low_atr NUMERIC,
        distance_to_weekly_high_atr NUMERIC,
        distance_to_weekly_low_atr NUMERIC,
        distance_to_4h_high_atr NUMERIC,
        distance_to_4h_low_atr NUMERIC,
        distance_to_next_htf_obstacle_atr NUMERIC,
        prev_session_high NUMERIC,
        prev_session_low NUMERIC,
        distance_to_prev_session_high_atr NUMERIC,
        distance_to_prev_session_low_atr NUMERIC,
        trend_age_bars_1h INTEGER,
        trend_age_impulses INTEGER,
        recent_trend_payoff_atr_24h NUMERIC,
        recent_trend_payoff_atr_48h NUMERIC,
        session_directional_bias NUMERIC,
        aoi_time_since_last_touch INTEGER,
        aoi_last_reaction_strength NUMERIC,
        distance_from_last_impulse_atr NUMERIC,
        htf_range_size_daily_atr NUMERIC,
        htf_range_size_weekly_atr NUMERIC,
        aoi_midpoint_range_position_daily NUMERIC,
        aoi_midpoint_range_position_weekly NUMERIC,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    )
"""


