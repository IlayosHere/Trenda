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
    SELECT lower_bound, upper_bound
    FROM trenda.area_of_interest
    WHERE forex_id = (SELECT id FROM trenda.forex WHERE name = %s)
    AND type_id = (SELECT id FROM trenda.aoi_type WHERE type = 'tradable')
    ORDER BY lower_bound ASC
"""

FETCH_TREND_LEVELS = """
    SELECT high, low
    FROM trenda.trend_data
    WHERE forex_id = (SELECT id FROM forex WHERE name = %s)
      AND timeframe_id = (SELECT id FROM timeframes WHERE type = %s)
"""

INSERT_TREND_SNAPSHOT = """
    INSERT INTO trenda.signal_trend (trend_4h, trend_1d, trend_1w)
    VALUES (%s, %s, %s)
    RETURNING id
"""

INSERT_ENTRY_SIGNAL = """
    INSERT INTO trenda.entry_signal (symbol, signal_time, signal_trend_id, aoi_high,
    aoi_low, trade_quality, is_success)
    VALUES (%s, %s, %s, %s, %s, %s, NULL)
    RETURNING id
"""

INSERT_ENTRY_CANDLE = """
    INSERT INTO trenda.entry_signal_cnadles
        (entry_signal_id, cnalde_number, high, low, open, close)
    VALUES (%s, %s, %s, %s, %s, %s)
"""
