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

INSERT_ENTRY_SIGNAL = """
    INSERT INTO trenda.entry_signal (
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

INSERT_ENTRY_SIGNAL_SCORE = """
    INSERT INTO trenda.entry_signal_score (
        entry_signal_id, stage_name, raw_score, weight, weighted_score
    )
    VALUES (%s, %s, %s, %s, %s)
"""

# Signal outcome queries
FETCH_PENDING_SIGNALS = """
    SELECT id, symbol, signal_time, direction, entry_price, atr_1h,
           aoi_low, aoi_high, aoi_effective_sl_distance_price
    FROM trenda.entry_signal
    WHERE outcome_computed = FALSE
    ORDER BY signal_time ASC
    LIMIT %s
"""

INSERT_SIGNAL_OUTCOME = """
    INSERT INTO trenda.signal_outcome (
        entry_signal_id, window_bars,
        mfe_atr, mae_atr,
        bars_to_mfe, bars_to_mae, first_extreme,
        return_after_3, return_after_6, return_after_12, return_after_24, return_end_window,
        bars_to_aoi_sl_hit, bars_to_r_1, bars_to_r_1_5, bars_to_r_2, aoi_rr_outcome
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (entry_signal_id) DO NOTHING
"""

MARK_OUTCOME_COMPUTED = """
    UPDATE trenda.entry_signal
    SET outcome_computed = TRUE
    WHERE id = %s
"""


