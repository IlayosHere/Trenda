UPDATE_TREND_DATA = """
    INSERT INTO trenda.trend_data (forex_id, timeframe_id, trend, high, low, last_updated)
    VALUES (
        (SELECT id FROM trenda.forex WHERE name = %s),
        (SELECT id FROM trenda.timeframes WHERE type = %s),
        %s, %s, %s, CURRENT_TIMESTAMP
    )
    ON CONFLICT (forex_id, timeframe_id) DO UPDATE SET
        trend = excluded.trend,
        high = excluded.high,
        low = excluded.low,
        last_updated = CURRENT_TIMESTAMP
"""

CLEAR_AOIS = """
    DELETE FROM trenda.area_of_interest
    WHERE forex_id = (SELECT id FROM trenda.forex WHERE name = %s)
      AND timeframe_id = (SELECT id FROM trenda.timeframes WHERE type = %s)
"""

UPSERT_AOIS = """
    INSERT INTO trenda.area_of_interest
        (forex_id, timeframe_id, lower_bound, upper_bound, type_id, last_updated)
    VALUES (
        (SELECT id FROM trenda.forex WHERE name = %s),
        (SELECT id FROM trenda.timeframes WHERE type = %s),
        %s,
        %s,
        (SELECT id FROM trenda.aoi_type WHERE type = %s),
        CURRENT_TIMESTAMP
    )
"""

FETCH_TREND_BIAS = """
    SELECT trend
    FROM trenda.trend_data
    WHERE forex_id = (SELECT id FROM forex WHERE name = %s)
      AND timeframe_id = (SELECT id FROM timeframes WHERE type = %s)
"""

FETCH_TRADABLE_AOIS = """
    SELECT 
        aoi.lower_bound, 
        aoi.upper_bound,
        tf.type as timeframe,
        at.type as classification
    FROM trenda.area_of_interest aoi
    JOIN trenda.timeframes tf ON aoi.timeframe_id = tf.id
    JOIN trenda.aoi_type at ON aoi.type_id = at.id
    WHERE aoi.forex_id = (SELECT id FROM trenda.forex WHERE name = %s)
    AND aoi.type_id = (SELECT id FROM trenda.aoi_type WHERE type = 'tradable')
    ORDER BY aoi.lower_bound ASC
"""

FETCH_TREND_LEVELS = """
    SELECT high, low
    FROM trenda.trend_data
    WHERE forex_id = (SELECT id FROM forex WHERE name = %s)
      AND timeframe_id = (SELECT id FROM timeframes WHERE type = %s)
"""

# Entry signal insert (stores complete execution data in one go)
INSERT_ENTRY_SIGNAL = """
    INSERT INTO trenda.entry_signal (
        symbol, signal_time, direction,
        aoi_timeframe, aoi_low, aoi_high,
        entry_price, atr_1h,
        htf_score, obstacle_score, total_score,
        sl_model, sl_distance_atr, tp_distance_atr, rr_multiple,
        is_break_candle_last,
        htf_range_position_daily, htf_range_position_weekly,
        distance_to_next_htf_obstacle_atr, conflicted_tf
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    RETURNING id
"""

# Signal outcome queries (96 bar window)
FETCH_PENDING_SIGNALS = """
    SELECT id, symbol, signal_time, direction, entry_price, atr_1h,
           aoi_low, aoi_high, sl_distance_atr
    FROM trenda.entry_signal
    WHERE outcome_computed = FALSE
      AND entry_price IS NOT NULL
    ORDER BY signal_time ASC
    LIMIT %s
"""

INSERT_SIGNAL_OUTCOME = """
    INSERT INTO trenda.signal_outcome (
        entry_signal_id, window_bars,
        mfe_atr, mae_atr,
        bars_to_mfe, bars_to_mae, first_extreme,
        return_after_48, return_after_72, return_after_96,
        exit_reason, bars_to_exit
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (entry_signal_id) DO NOTHING
"""

MARK_OUTCOME_COMPUTED = """
    UPDATE trenda.entry_signal
    SET outcome_computed = TRUE
    WHERE id = %s
"""
