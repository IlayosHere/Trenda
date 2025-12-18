"""SQL queries for replay schema operations.

All queries target the trenda_replay schema instead of trenda.
Mirrors production queries from database/queries.py.
"""

from .config import SCHEMA_NAME

# =============================================================================
# Entry Signal Queries
# =============================================================================

CHECK_SIGNAL_EXISTS = f"""
    SELECT EXISTS(
        SELECT 1 FROM {SCHEMA_NAME}.entry_signal
        WHERE symbol = %s AND signal_time = %s
    )
"""

INSERT_REPLAY_ENTRY_SIGNAL = f"""
    INSERT INTO {SCHEMA_NAME}.entry_signal (
        symbol, signal_time, direction,
        trend_4h, trend_1d, trend_1w, trend_alignment_strength,
        aoi_timeframe, aoi_low, aoi_high, aoi_classification,
        entry_price, atr_1h,
        final_score, tier,
        is_break_candle_last,
        aoi_sl_tolerance_atr, aoi_raw_sl_distance_price, aoi_raw_sl_distance_atr,
        aoi_effective_sl_distance_price, aoi_effective_sl_distance_atr
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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

FETCH_PENDING_REPLAY_SIGNALS = f"""
    SELECT id, symbol, signal_time, direction, entry_price, atr_1h,
           aoi_low, aoi_high, aoi_effective_sl_distance_price
    FROM {SCHEMA_NAME}.entry_signal
    WHERE outcome_computed = FALSE
    ORDER BY signal_time ASC
    LIMIT %s
"""

FETCH_SIGNAL_BY_ID = f"""
    SELECT id, symbol, signal_time, direction, entry_price, atr_1h,
           aoi_low, aoi_high, aoi_effective_sl_distance_price
    FROM {SCHEMA_NAME}.entry_signal
    WHERE id = %s
"""

INSERT_REPLAY_SIGNAL_OUTCOME = f"""
    INSERT INTO {SCHEMA_NAME}.signal_outcome (
        entry_signal_id, window_bars,
        mfe_atr, mae_atr,
        bars_to_mfe, bars_to_mae, first_extreme,
        return_after_3, return_after_6, return_after_12, return_after_24, return_end_window,
        bars_to_aoi_sl_hit, bars_to_r_1, bars_to_r_1_5, bars_to_r_2, aoi_rr_outcome
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (entry_signal_id) DO NOTHING
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
        aoi_sl_tolerance_atr NUMERIC,
        aoi_raw_sl_distance_price NUMERIC,
        aoi_raw_sl_distance_atr NUMERIC,
        aoi_effective_sl_distance_price NUMERIC,
        aoi_effective_sl_distance_atr NUMERIC,
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
        return_after_3 NUMERIC,
        return_after_6 NUMERIC,
        return_after_12 NUMERIC,
        return_after_24 NUMERIC,
        return_end_window NUMERIC,
        bars_to_aoi_sl_hit INTEGER,
        bars_to_r_1 INTEGER,
        bars_to_r_1_5 INTEGER,
        bars_to_r_2 INTEGER,
        aoi_rr_outcome VARCHAR(30),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    )
"""
