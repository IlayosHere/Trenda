-- =============================================================================
-- VALIDATE 2023 HOLDOUT — Top 3 Configurations
-- =============================================================================
-- Run after replay completes on 2023 data.
-- Tables: trenda_replay.entry_signal (es), pre_entry_context_v2 (pec),
--         sl_geometry_unbiased (sg), exit_simulation_unbiased (esi)
--
-- Configs:
--   #1: Per-group MILD bull gates + excl h17-20 UTC + tc≤3 bear
--   #2: Baseline gates (sbias≥0 bull, tc≤3 bear) + excl h17-20 UTC
--   #3: Per-group MILD bull gates + excl h12-14 UTC + tc≤3 bear
-- =============================================================================


-- ===========================
-- HELPER VIEW: Base join (2023 only)
-- ===========================
-- Use this CTE in all queries below
-- rr_multiple = 2.0, is_break_candle_last = TRUE, sl_model_version = 'CHECK_GEO'
-- Year = 2023

-- ===========================
-- QUERY 1: Unfiltered 2023 baseline (no gates, no portfolio)
-- ===========================
WITH base AS (
    SELECT
        es.id,
        es.signal_time,
        es.symbol,
        es.direction,
        es.hour_of_day_utc,
        es.aoi_touch_count_since_creation,
        pec.htf_range_position_mid,
        pec.session_directional_bias,
        pec.aoi_height_atr,
        pec.aoi_time_since_last_touch,
        pec.distance_from_last_impulse_atr,
        sg.signal_candle_opposite_extreme_atr,
        esi.sl_model,
        esi.exit_reason,
        esi.return_r,
        esi.exit_bar
    FROM trenda_replay.entry_signal es
    JOIN trenda_replay.pre_entry_context_v2 pec ON pec.entry_signal_id = es.id
    JOIN trenda_replay.sl_geometry_unbiased sg ON sg.entry_signal_id = es.id
    JOIN trenda_replay.exit_simulation_unbiased esi ON esi.entry_signal_id = es.id
    WHERE es.is_break_candle_last = TRUE
      AND es.sl_model_version = 'CHECK_GEO'
      AND esi.rr_multiple = 2.0
      AND EXTRACT(YEAR FROM es.signal_time) = 2023
)
SELECT
    COUNT(*) AS total_trades,
    ROUND(100.0 * SUM(CASE WHEN exit_reason = 'TP' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2) AS win_pct,
    ROUND(AVG(return_r)::numeric, 4) AS exp_r,
    ROUND(SUM(CASE WHEN return_r > 0 THEN return_r ELSE 0 END) /
          NULLIF(ABS(SUM(CASE WHEN return_r < 0 THEN return_r ELSE 0 END)), 0)::numeric, 3) AS profit_factor
FROM base;


-- ===========================
-- QUERY 2: CONFIG #2 — Baseline gates + excl h17-20
-- (simplest — tc≤3 bear, sbias≥0 bull, exclude hours 17,18,19)
-- ===========================
WITH base AS (
    SELECT
        es.id, es.signal_time, es.symbol, es.direction, es.hour_of_day_utc,
        es.aoi_touch_count_since_creation,
        pec.htf_range_position_mid, pec.session_directional_bias,
        pec.aoi_height_atr, pec.distance_from_last_impulse_atr,
        sg.signal_candle_opposite_extreme_atr,
        esi.sl_model, esi.exit_reason, esi.return_r, esi.exit_bar
    FROM trenda_replay.entry_signal es
    JOIN trenda_replay.pre_entry_context_v2 pec ON pec.entry_signal_id = es.id
    JOIN trenda_replay.sl_geometry_unbiased sg ON sg.entry_signal_id = es.id
    JOIN trenda_replay.exit_simulation_unbiased esi ON esi.entry_signal_id = es.id
    WHERE es.is_break_candle_last = TRUE
      AND es.sl_model_version = 'CHECK_GEO'
      AND esi.rr_multiple = 2.0
      AND EXTRACT(YEAR FROM es.signal_time) = 2023
),
gated AS (
    SELECT * FROM base
    WHERE (
        -- Bear gate: tc <= 3
        (direction = 'bearish' AND aoi_touch_count_since_creation <= 3)
        OR
        -- Bull gate: sbias >= 0
        (direction = 'bullish' AND session_directional_bias >= 0.0)
    )
    -- Global hour exclusion: 17, 18, 19
    AND hour_of_day_utc NOT IN (17, 18, 19)
),
portfolio AS (
    SELECT * FROM gated
    WHERE
    -- BEAR BUCKETS (10 buckets from tuned_window_configs.csv)
    (
        -- jpy_pairs | bearish | discount | SL_ATR_0_5 | h06+3h
        (symbol IN ('AUDJPY','CADJPY','CHFJPY','EURJPY','GBPJPY','NZDJPY','USDJPY')
         AND direction = 'bearish'
         AND htf_range_position_mid <= 0.25
         AND sl_model = 'SL_ATR_0_5'
         AND hour_of_day_utc IN (6,7,8))

        OR
        -- jpy_pairs | bearish | premium | SL_ATR_1_0 | h04+5h
        (symbol IN ('AUDJPY','CADJPY','CHFJPY','EURJPY','GBPJPY','NZDJPY','USDJPY')
         AND direction = 'bearish'
         AND htf_range_position_mid >= 0.75
         AND sl_model = 'SL_ATR_1_0'
         AND hour_of_day_utc IN (4,5,6,7,8))

        OR
        -- usd_majors | bearish | discount | SL_AOI_NEAR_PLUS_0_25 | h14,15,18
        (symbol IN ('AUDUSD','EURUSD','GBPUSD','NZDUSD','USDCAD','USDCHF')
         AND direction = 'bearish'
         AND htf_range_position_mid <= 0.25
         AND sl_model = 'SL_AOI_NEAR_PLUS_0_25'
         AND hour_of_day_utc IN (14,15,18))

        OR
        -- usd_majors | bearish | premium | SL_SIGNAL_CANDLE | h1,16-22
        (symbol IN ('AUDUSD','EURUSD','GBPUSD','NZDUSD','USDCAD','USDCHF')
         AND direction = 'bearish'
         AND htf_range_position_mid >= 0.75
         AND sl_model = 'SL_SIGNAL_CANDLE'
         AND hour_of_day_utc IN (1,16,17,18,19,20,21,22))

        OR
        -- eur_crosses | bearish | discount | SL_AOI_NEAR_PLUS_0_5 | h0,17,18,21,22,23
        (symbol IN ('EURAUD','EURCAD','EURCHF','EURGBP','EURNZD')
         AND direction = 'bearish'
         AND htf_range_position_mid <= 0.25
         AND sl_model = 'SL_AOI_NEAR_PLUS_0_5'
         AND hour_of_day_utc IN (0,17,18,21,22,23))

        OR
        -- eur_crosses | bearish | premium | SL_AOI_FAR | h1-9
        (symbol IN ('EURAUD','EURCAD','EURCHF','EURGBP','EURNZD')
         AND direction = 'bearish'
         AND htf_range_position_mid >= 0.75
         AND sl_model = 'SL_AOI_FAR'
         AND hour_of_day_utc IN (1,2,3,4,5,6,7,8,9))

        OR
        -- gbp_crosses | bearish | discount | SL_ATR_1_0 | h2,3,4,22,23
        (symbol IN ('GBPAUD','GBPCAD','GBPCHF','GBPNZD')
         AND direction = 'bearish'
         AND htf_range_position_mid <= 0.25
         AND sl_model = 'SL_ATR_1_0'
         AND hour_of_day_utc IN (2,3,4,22,23))

        OR
        -- gbp_crosses | bearish | premium | SL_ATR_0_5 | h0,16-19,22,23
        (symbol IN ('GBPAUD','GBPCAD','GBPCHF','GBPNZD')
         AND direction = 'bearish'
         AND htf_range_position_mid >= 0.75
         AND sl_model = 'SL_ATR_0_5'
         AND hour_of_day_utc IN (0,16,17,18,19,22,23))

        OR
        -- commodity | bearish | discount | SL_ATR_2_0 | h1-5,7-9
        (symbol IN ('AUDCAD','AUDCHF','NZDCAD','NZDCHF')
         AND direction = 'bearish'
         AND htf_range_position_mid <= 0.25
         AND sl_model = 'SL_ATR_2_0'
         AND hour_of_day_utc IN (1,2,3,4,5,7,8,9))

        OR
        -- commodity | bearish | premium | SL_ATR_0_5 | h0,1,3-5,18-23
        (symbol IN ('AUDCAD','AUDCHF','NZDCAD','NZDCHF')
         AND direction = 'bearish'
         AND htf_range_position_mid >= 0.75
         AND sl_model = 'SL_ATR_0_5'
         AND hour_of_day_utc IN (0,1,3,4,5,18,19,20,21,22,23))
    )
    OR
    -- BULL BUCKETS (10 buckets)
    (
        -- jpy_pairs | bullish | discount | SL_SIGNAL_CANDLE_PLUS_0_25 | h0,1,12-14
        (symbol IN ('AUDJPY','CADJPY','CHFJPY','EURJPY','GBPJPY','NZDJPY','USDJPY')
         AND direction = 'bullish'
         AND htf_range_position_mid <= 0.25
         AND sl_model = 'SL_SIGNAL_CANDLE_PLUS_0_25'
         AND hour_of_day_utc IN (0,1,12,13,14))

        OR
        -- jpy_pairs | bullish | premium | SL_AOI_NEAR_PLUS_0_25 | h4,5,6
        (symbol IN ('AUDJPY','CADJPY','CHFJPY','EURJPY','GBPJPY','NZDJPY','USDJPY')
         AND direction = 'bullish'
         AND htf_range_position_mid >= 0.75
         AND sl_model = 'SL_AOI_NEAR_PLUS_0_25'
         AND hour_of_day_utc IN (4,5,6))

        OR
        -- usd_majors | bullish | discount | SL_SIGNAL_CANDLE | h0,1,12-15
        (symbol IN ('AUDUSD','EURUSD','GBPUSD','NZDUSD','USDCAD','USDCHF')
         AND direction = 'bullish'
         AND htf_range_position_mid <= 0.25
         AND sl_model = 'SL_SIGNAL_CANDLE'
         AND hour_of_day_utc IN (0,1,12,13,14,15))

        OR
        -- usd_majors | bullish | premium | SL_ATR_0_5 | h6,7,8
        (symbol IN ('AUDUSD','EURUSD','GBPUSD','NZDUSD','USDCAD','USDCHF')
         AND direction = 'bullish'
         AND htf_range_position_mid >= 0.75
         AND sl_model = 'SL_ATR_0_5'
         AND hour_of_day_utc IN (6,7,8))

        OR
        -- eur_crosses | bullish | discount | SL_ATR_1_5 | h0,1,3,4,5
        (symbol IN ('EURAUD','EURCAD','EURCHF','EURGBP','EURNZD')
         AND direction = 'bullish'
         AND htf_range_position_mid <= 0.25
         AND sl_model = 'SL_ATR_1_5'
         AND hour_of_day_utc IN (0,1,3,4,5))

        OR
        -- eur_crosses | bullish | premium | SL_AOI_NEAR_PLUS_0_5 | h5,6,9
        (symbol IN ('EURAUD','EURCAD','EURCHF','EURGBP','EURNZD')
         AND direction = 'bullish'
         AND htf_range_position_mid >= 0.75
         AND sl_model = 'SL_AOI_NEAR_PLUS_0_5'
         AND hour_of_day_utc IN (5,6,9))

        OR
        -- gbp_crosses | bullish | discount | SL_SIGNAL_CANDLE_PLUS_0_25 | h0,1,5-10
        (symbol IN ('GBPAUD','GBPCAD','GBPCHF','GBPNZD')
         AND direction = 'bullish'
         AND htf_range_position_mid <= 0.25
         AND sl_model = 'SL_SIGNAL_CANDLE_PLUS_0_25'
         AND hour_of_day_utc IN (0,1,5,6,7,8,9,10))

        OR
        -- gbp_crosses | bullish | premium | SL_ATR_2_0 | h12,14,15
        (symbol IN ('GBPAUD','GBPCAD','GBPCHF','GBPNZD')
         AND direction = 'bullish'
         AND htf_range_position_mid >= 0.75
         AND sl_model = 'SL_ATR_2_0'
         AND hour_of_day_utc IN (12,14,15))

        OR
        -- commodity | bullish | discount | SL_ATR_1_0 | h0-6,21
        (symbol IN ('AUDCAD','AUDCHF','NZDCAD','NZDCHF')
         AND direction = 'bullish'
         AND htf_range_position_mid <= 0.25
         AND sl_model = 'SL_ATR_1_0'
         AND hour_of_day_utc IN (0,1,2,3,4,5,6,21))

        OR
        -- commodity | bullish | premium | SL_ATR_0_5 | h21,22,23
        (symbol IN ('AUDCAD','AUDCHF','NZDCAD','NZDCHF')
         AND direction = 'bullish'
         AND htf_range_position_mid >= 0.75
         AND sl_model = 'SL_ATR_0_5'
         AND hour_of_day_utc IN (21,22,23))
    )
)
SELECT
    'Config #2: Baseline + excl_h17-20' AS config,
    COUNT(*) AS trades,
    ROUND(100.0 * SUM(CASE WHEN exit_reason = 'TP' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2) AS win_pct,
    ROUND(AVG(return_r)::numeric, 4) AS exp_r,
    ROUND(SUM(CASE WHEN return_r > 0 THEN return_r ELSE 0 END) /
          NULLIF(ABS(SUM(CASE WHEN return_r < 0 THEN return_r ELSE 0 END)), 0)::numeric, 3) AS pf
FROM portfolio;


-- ===========================
-- QUERY 3: CONFIG #1 — MILD bull gates + excl h17-20
-- Same portfolio BUT with per-group bull gates applied
-- ===========================
WITH base AS (
    SELECT
        es.id, es.signal_time, es.symbol, es.direction, es.hour_of_day_utc,
        es.aoi_touch_count_since_creation,
        pec.htf_range_position_mid, pec.session_directional_bias,
        pec.aoi_height_atr, pec.distance_from_last_impulse_atr,
        sg.signal_candle_opposite_extreme_atr,
        esi.sl_model, esi.exit_reason, esi.return_r, esi.exit_bar
    FROM trenda_replay.entry_signal es
    JOIN trenda_replay.pre_entry_context_v2 pec ON pec.entry_signal_id = es.id
    JOIN trenda_replay.sl_geometry_unbiased sg ON sg.entry_signal_id = es.id
    JOIN trenda_replay.exit_simulation_unbiased esi ON esi.entry_signal_id = es.id
    WHERE es.is_break_candle_last = TRUE
      AND es.sl_model_version = 'CHECK_GEO'
      AND esi.rr_multiple = 2.0
      AND EXTRACT(YEAR FROM es.signal_time) = 2023
),
gated AS (
    SELECT * FROM base
    WHERE (
        -- Bear gate: tc <= 3 (all groups)
        (direction = 'bearish' AND aoi_touch_count_since_creation <= 3)
        OR
        -- Bull gates: per-group MILD
        -- jpy_pairs: opp_extreme <= 0.7
        (direction = 'bullish' AND session_directional_bias >= 0.0
         AND symbol IN ('AUDJPY','CADJPY','CHFJPY','EURJPY','GBPJPY','NZDJPY','USDJPY')
         AND signal_candle_opposite_extreme_atr <= 0.7)
        OR
        -- usd_majors: sbias >= 0.2
        (direction = 'bullish'
         AND symbol IN ('AUDUSD','EURUSD','GBPUSD','NZDUSD','USDCAD','USDCHF')
         AND session_directional_bias >= 0.2)
        OR
        -- eur_crosses: height <= 1.3
        (direction = 'bullish' AND session_directional_bias >= 0.0
         AND symbol IN ('EURAUD','EURCAD','EURCHF','EURGBP','EURNZD')
         AND aoi_height_atr <= 1.3)
        OR
        -- gbp_crosses: sbias >= 0.1
        (direction = 'bullish'
         AND symbol IN ('GBPAUD','GBPCAD','GBPCHF','GBPNZD')
         AND session_directional_bias >= 0.1)
        OR
        -- commodity: pass-through (sbias >= 0)
        (direction = 'bullish' AND session_directional_bias >= 0.0
         AND symbol IN ('AUDCAD','AUDCHF','NZDCAD','NZDCHF'))
    )
    -- Global hour exclusion: 17, 18, 19
    AND hour_of_day_utc NOT IN (17, 18, 19)
),
portfolio AS (
    SELECT * FROM gated
    WHERE
    -- Same portfolio buckets as Config #2 above (bear + bull)
    -- BEAR BUCKETS
    (
        (symbol IN ('AUDJPY','CADJPY','CHFJPY','EURJPY','GBPJPY','NZDJPY','USDJPY')
         AND direction = 'bearish' AND htf_range_position_mid <= 0.25
         AND sl_model = 'SL_ATR_0_5' AND hour_of_day_utc IN (6,7,8))
        OR
        (symbol IN ('AUDJPY','CADJPY','CHFJPY','EURJPY','GBPJPY','NZDJPY','USDJPY')
         AND direction = 'bearish' AND htf_range_position_mid >= 0.75
         AND sl_model = 'SL_ATR_1_0' AND hour_of_day_utc IN (4,5,6,7,8))
        OR
        (symbol IN ('AUDUSD','EURUSD','GBPUSD','NZDUSD','USDCAD','USDCHF')
         AND direction = 'bearish' AND htf_range_position_mid <= 0.25
         AND sl_model = 'SL_AOI_NEAR_PLUS_0_25' AND hour_of_day_utc IN (14,15,18))
        OR
        (symbol IN ('AUDUSD','EURUSD','GBPUSD','NZDUSD','USDCAD','USDCHF')
         AND direction = 'bearish' AND htf_range_position_mid >= 0.75
         AND sl_model = 'SL_SIGNAL_CANDLE' AND hour_of_day_utc IN (1,16,17,18,19,20,21,22))
        OR
        (symbol IN ('EURAUD','EURCAD','EURCHF','EURGBP','EURNZD')
         AND direction = 'bearish' AND htf_range_position_mid <= 0.25
         AND sl_model = 'SL_AOI_NEAR_PLUS_0_5' AND hour_of_day_utc IN (0,17,18,21,22,23))
        OR
        (symbol IN ('EURAUD','EURCAD','EURCHF','EURGBP','EURNZD')
         AND direction = 'bearish' AND htf_range_position_mid >= 0.75
         AND sl_model = 'SL_AOI_FAR' AND hour_of_day_utc IN (1,2,3,4,5,6,7,8,9))
        OR
        (symbol IN ('GBPAUD','GBPCAD','GBPCHF','GBPNZD')
         AND direction = 'bearish' AND htf_range_position_mid <= 0.25
         AND sl_model = 'SL_ATR_1_0' AND hour_of_day_utc IN (2,3,4,22,23))
        OR
        (symbol IN ('GBPAUD','GBPCAD','GBPCHF','GBPNZD')
         AND direction = 'bearish' AND htf_range_position_mid >= 0.75
         AND sl_model = 'SL_ATR_0_5' AND hour_of_day_utc IN (0,16,17,18,19,22,23))
        OR
        (symbol IN ('AUDCAD','AUDCHF','NZDCAD','NZDCHF')
         AND direction = 'bearish' AND htf_range_position_mid <= 0.25
         AND sl_model = 'SL_ATR_2_0' AND hour_of_day_utc IN (1,2,3,4,5,7,8,9))
        OR
        (symbol IN ('AUDCAD','AUDCHF','NZDCAD','NZDCHF')
         AND direction = 'bearish' AND htf_range_position_mid >= 0.75
         AND sl_model = 'SL_ATR_0_5' AND hour_of_day_utc IN (0,1,3,4,5,18,19,20,21,22,23))
    )
    OR
    -- BULL BUCKETS
    (
        (symbol IN ('AUDJPY','CADJPY','CHFJPY','EURJPY','GBPJPY','NZDJPY','USDJPY')
         AND direction = 'bullish' AND htf_range_position_mid <= 0.25
         AND sl_model = 'SL_SIGNAL_CANDLE_PLUS_0_25' AND hour_of_day_utc IN (0,1,12,13,14))
        OR
        (symbol IN ('AUDJPY','CADJPY','CHFJPY','EURJPY','GBPJPY','NZDJPY','USDJPY')
         AND direction = 'bullish' AND htf_range_position_mid >= 0.75
         AND sl_model = 'SL_AOI_NEAR_PLUS_0_25' AND hour_of_day_utc IN (4,5,6))
        OR
        (symbol IN ('AUDUSD','EURUSD','GBPUSD','NZDUSD','USDCAD','USDCHF')
         AND direction = 'bullish' AND htf_range_position_mid <= 0.25
         AND sl_model = 'SL_SIGNAL_CANDLE' AND hour_of_day_utc IN (0,1,12,13,14,15))
        OR
        (symbol IN ('AUDUSD','EURUSD','GBPUSD','NZDUSD','USDCAD','USDCHF')
         AND direction = 'bullish' AND htf_range_position_mid >= 0.75
         AND sl_model = 'SL_ATR_0_5' AND hour_of_day_utc IN (6,7,8))
        OR
        (symbol IN ('EURAUD','EURCAD','EURCHF','EURGBP','EURNZD')
         AND direction = 'bullish' AND htf_range_position_mid <= 0.25
         AND sl_model = 'SL_ATR_1_5' AND hour_of_day_utc IN (0,1,3,4,5))
        OR
        (symbol IN ('EURAUD','EURCAD','EURCHF','EURGBP','EURNZD')
         AND direction = 'bullish' AND htf_range_position_mid >= 0.75
         AND sl_model = 'SL_AOI_NEAR_PLUS_0_5' AND hour_of_day_utc IN (5,6,9))
        OR
        (symbol IN ('GBPAUD','GBPCAD','GBPCHF','GBPNZD')
         AND direction = 'bullish' AND htf_range_position_mid <= 0.25
         AND sl_model = 'SL_SIGNAL_CANDLE_PLUS_0_25' AND hour_of_day_utc IN (0,1,5,6,7,8,9,10))
        OR
        (symbol IN ('GBPAUD','GBPCAD','GBPCHF','GBPNZD')
         AND direction = 'bullish' AND htf_range_position_mid >= 0.75
         AND sl_model = 'SL_ATR_2_0' AND hour_of_day_utc IN (12,14,15))
        OR
        (symbol IN ('AUDCAD','AUDCHF','NZDCAD','NZDCHF')
         AND direction = 'bullish' AND htf_range_position_mid <= 0.25
         AND sl_model = 'SL_ATR_1_0' AND hour_of_day_utc IN (0,1,2,3,4,5,6,21))
        OR
        (symbol IN ('AUDCAD','AUDCHF','NZDCAD','NZDCHF')
         AND direction = 'bullish' AND htf_range_position_mid >= 0.75
         AND sl_model = 'SL_ATR_0_5' AND hour_of_day_utc IN (21,22,23))
    )
)
SELECT
    'Config #1: MILD bull + excl_h17-20' AS config,
    COUNT(*) AS trades,
    ROUND(100.0 * SUM(CASE WHEN exit_reason = 'TP' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2) AS win_pct,
    ROUND(AVG(return_r)::numeric, 4) AS exp_r,
    ROUND(SUM(CASE WHEN return_r > 0 THEN return_r ELSE 0 END) /
          NULLIF(ABS(SUM(CASE WHEN return_r < 0 THEN return_r ELSE 0 END)), 0)::numeric, 3) AS pf
FROM portfolio;


-- ===========================
-- QUERY 4: CONFIG #3 — MILD bull gates + excl h12-14
-- Same as Config #1 but exclude hours 12,13 instead of 17,18,19
-- ===========================
WITH base AS (
    SELECT
        es.id, es.signal_time, es.symbol, es.direction, es.hour_of_day_utc,
        es.aoi_touch_count_since_creation,
        pec.htf_range_position_mid, pec.session_directional_bias,
        pec.aoi_height_atr, pec.distance_from_last_impulse_atr,
        sg.signal_candle_opposite_extreme_atr,
        esi.sl_model, esi.exit_reason, esi.return_r, esi.exit_bar
    FROM trenda_replay.entry_signal es
    JOIN trenda_replay.pre_entry_context_v2 pec ON pec.entry_signal_id = es.id
    JOIN trenda_replay.sl_geometry_unbiased sg ON sg.entry_signal_id = es.id
    JOIN trenda_replay.exit_simulation_unbiased esi ON esi.entry_signal_id = es.id
    WHERE es.is_break_candle_last = TRUE
      AND es.sl_model_version = 'CHECK_GEO'
      AND esi.rr_multiple = 2.0
      AND EXTRACT(YEAR FROM es.signal_time) = 2023
),
gated AS (
    SELECT * FROM base
    WHERE (
        (direction = 'bearish' AND aoi_touch_count_since_creation <= 3)
        OR
        (direction = 'bullish' AND session_directional_bias >= 0.0
         AND symbol IN ('AUDJPY','CADJPY','CHFJPY','EURJPY','GBPJPY','NZDJPY','USDJPY')
         AND signal_candle_opposite_extreme_atr <= 0.7)
        OR
        (direction = 'bullish'
         AND symbol IN ('AUDUSD','EURUSD','GBPUSD','NZDUSD','USDCAD','USDCHF')
         AND session_directional_bias >= 0.2)
        OR
        (direction = 'bullish' AND session_directional_bias >= 0.0
         AND symbol IN ('EURAUD','EURCAD','EURCHF','EURGBP','EURNZD')
         AND aoi_height_atr <= 1.3)
        OR
        (direction = 'bullish'
         AND symbol IN ('GBPAUD','GBPCAD','GBPCHF','GBPNZD')
         AND session_directional_bias >= 0.1)
        OR
        (direction = 'bullish' AND session_directional_bias >= 0.0
         AND symbol IN ('AUDCAD','AUDCHF','NZDCAD','NZDCHF'))
    )
    -- Global hour exclusion: 12, 13
    AND hour_of_day_utc NOT IN (12, 13)
),
portfolio AS (
    SELECT * FROM gated
    WHERE
    -- Same portfolio bucket definitions (bear + bull)
    (
        (symbol IN ('AUDJPY','CADJPY','CHFJPY','EURJPY','GBPJPY','NZDJPY','USDJPY')
         AND direction = 'bearish' AND htf_range_position_mid <= 0.25
         AND sl_model = 'SL_ATR_0_5' AND hour_of_day_utc IN (6,7,8))
        OR
        (symbol IN ('AUDJPY','CADJPY','CHFJPY','EURJPY','GBPJPY','NZDJPY','USDJPY')
         AND direction = 'bearish' AND htf_range_position_mid >= 0.75
         AND sl_model = 'SL_ATR_1_0' AND hour_of_day_utc IN (4,5,6,7,8))
        OR
        (symbol IN ('AUDUSD','EURUSD','GBPUSD','NZDUSD','USDCAD','USDCHF')
         AND direction = 'bearish' AND htf_range_position_mid <= 0.25
         AND sl_model = 'SL_AOI_NEAR_PLUS_0_25' AND hour_of_day_utc IN (14,15,18))
        OR
        (symbol IN ('AUDUSD','EURUSD','GBPUSD','NZDUSD','USDCAD','USDCHF')
         AND direction = 'bearish' AND htf_range_position_mid >= 0.75
         AND sl_model = 'SL_SIGNAL_CANDLE' AND hour_of_day_utc IN (1,16,17,18,19,20,21,22))
        OR
        (symbol IN ('EURAUD','EURCAD','EURCHF','EURGBP','EURNZD')
         AND direction = 'bearish' AND htf_range_position_mid <= 0.25
         AND sl_model = 'SL_AOI_NEAR_PLUS_0_5' AND hour_of_day_utc IN (0,17,18,21,22,23))
        OR
        (symbol IN ('EURAUD','EURCAD','EURCHF','EURGBP','EURNZD')
         AND direction = 'bearish' AND htf_range_position_mid >= 0.75
         AND sl_model = 'SL_AOI_FAR' AND hour_of_day_utc IN (1,2,3,4,5,6,7,8,9))
        OR
        (symbol IN ('GBPAUD','GBPCAD','GBPCHF','GBPNZD')
         AND direction = 'bearish' AND htf_range_position_mid <= 0.25
         AND sl_model = 'SL_ATR_1_0' AND hour_of_day_utc IN (2,3,4,22,23))
        OR
        (symbol IN ('GBPAUD','GBPCAD','GBPCHF','GBPNZD')
         AND direction = 'bearish' AND htf_range_position_mid >= 0.75
         AND sl_model = 'SL_ATR_0_5' AND hour_of_day_utc IN (0,16,17,18,19,22,23))
        OR
        (symbol IN ('AUDCAD','AUDCHF','NZDCAD','NZDCHF')
         AND direction = 'bearish' AND htf_range_position_mid <= 0.25
         AND sl_model = 'SL_ATR_2_0' AND hour_of_day_utc IN (1,2,3,4,5,7,8,9))
        OR
        (symbol IN ('AUDCAD','AUDCHF','NZDCAD','NZDCHF')
         AND direction = 'bearish' AND htf_range_position_mid >= 0.75
         AND sl_model = 'SL_ATR_0_5' AND hour_of_day_utc IN (0,1,3,4,5,18,19,20,21,22,23))
    )
    OR
    (
        (symbol IN ('AUDJPY','CADJPY','CHFJPY','EURJPY','GBPJPY','NZDJPY','USDJPY')
         AND direction = 'bullish' AND htf_range_position_mid <= 0.25
         AND sl_model = 'SL_SIGNAL_CANDLE_PLUS_0_25' AND hour_of_day_utc IN (0,1,12,13,14))
        OR
        (symbol IN ('AUDJPY','CADJPY','CHFJPY','EURJPY','GBPJPY','NZDJPY','USDJPY')
         AND direction = 'bullish' AND htf_range_position_mid >= 0.75
         AND sl_model = 'SL_AOI_NEAR_PLUS_0_25' AND hour_of_day_utc IN (4,5,6))
        OR
        (symbol IN ('AUDUSD','EURUSD','GBPUSD','NZDUSD','USDCAD','USDCHF')
         AND direction = 'bullish' AND htf_range_position_mid <= 0.25
         AND sl_model = 'SL_SIGNAL_CANDLE' AND hour_of_day_utc IN (0,1,12,13,14,15))
        OR
        (symbol IN ('AUDUSD','EURUSD','GBPUSD','NZDUSD','USDCAD','USDCHF')
         AND direction = 'bullish' AND htf_range_position_mid >= 0.75
         AND sl_model = 'SL_ATR_0_5' AND hour_of_day_utc IN (6,7,8))
        OR
        (symbol IN ('EURAUD','EURCAD','EURCHF','EURGBP','EURNZD')
         AND direction = 'bullish' AND htf_range_position_mid <= 0.25
         AND sl_model = 'SL_ATR_1_5' AND hour_of_day_utc IN (0,1,3,4,5))
        OR
        (symbol IN ('EURAUD','EURCAD','EURCHF','EURGBP','EURNZD')
         AND direction = 'bullish' AND htf_range_position_mid >= 0.75
         AND sl_model = 'SL_AOI_NEAR_PLUS_0_5' AND hour_of_day_utc IN (5,6,9))
        OR
        (symbol IN ('GBPAUD','GBPCAD','GBPCHF','GBPNZD')
         AND direction = 'bullish' AND htf_range_position_mid <= 0.25
         AND sl_model = 'SL_SIGNAL_CANDLE_PLUS_0_25' AND hour_of_day_utc IN (0,1,5,6,7,8,9,10))
        OR
        (symbol IN ('GBPAUD','GBPCAD','GBPCHF','GBPNZD')
         AND direction = 'bullish' AND htf_range_position_mid >= 0.75
         AND sl_model = 'SL_ATR_2_0' AND hour_of_day_utc IN (12,14,15))
        OR
        (symbol IN ('AUDCAD','AUDCHF','NZDCAD','NZDCHF')
         AND direction = 'bullish' AND htf_range_position_mid <= 0.25
         AND sl_model = 'SL_ATR_1_0' AND hour_of_day_utc IN (0,1,2,3,4,5,6,21))
        OR
        (symbol IN ('AUDCAD','AUDCHF','NZDCAD','NZDCHF')
         AND direction = 'bullish' AND htf_range_position_mid >= 0.75
         AND sl_model = 'SL_ATR_0_5' AND hour_of_day_utc IN (21,22,23))
    )
)
SELECT
    'Config #3: MILD bull + excl_h12-14' AS config,
    COUNT(*) AS trades,
    ROUND(100.0 * SUM(CASE WHEN exit_reason = 'TP' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2) AS win_pct,
    ROUND(AVG(return_r)::numeric, 4) AS exp_r,
    ROUND(SUM(CASE WHEN return_r > 0 THEN return_r ELSE 0 END) /
          NULLIF(ABS(SUM(CASE WHEN return_r < 0 THEN return_r ELSE 0 END)), 0)::numeric, 3) AS pf
FROM portfolio;


-- ===========================
-- QUERY 5: Per-direction breakdown for ALL 3 configs
-- ===========================

-- Config #1 per-direction
WITH base AS (
    SELECT es.id, es.signal_time, es.symbol, es.direction, es.hour_of_day_utc,
        es.aoi_touch_count_since_creation,
        pec.htf_range_position_mid, pec.session_directional_bias,
        pec.aoi_height_atr, pec.distance_from_last_impulse_atr,
        sg.signal_candle_opposite_extreme_atr,
        esi.sl_model, esi.exit_reason, esi.return_r
    FROM trenda_replay.entry_signal es
    JOIN trenda_replay.pre_entry_context_v2 pec ON pec.entry_signal_id = es.id
    JOIN trenda_replay.sl_geometry_unbiased sg ON sg.entry_signal_id = es.id
    JOIN trenda_replay.exit_simulation_unbiased esi ON esi.entry_signal_id = es.id
    WHERE es.is_break_candle_last = TRUE
      AND es.sl_model_version = 'CHECK_GEO'
      AND esi.rr_multiple = 2.0
      AND EXTRACT(YEAR FROM es.signal_time) = 2023
),
gated AS (
    SELECT * FROM base
    WHERE (
        (direction = 'bearish' AND aoi_touch_count_since_creation <= 3)
        OR
        (direction = 'bullish' AND session_directional_bias >= 0.0
         AND symbol IN ('AUDJPY','CADJPY','CHFJPY','EURJPY','GBPJPY','NZDJPY','USDJPY')
         AND signal_candle_opposite_extreme_atr <= 0.7)
        OR
        (direction = 'bullish'
         AND symbol IN ('AUDUSD','EURUSD','GBPUSD','NZDUSD','USDCAD','USDCHF')
         AND session_directional_bias >= 0.2)
        OR
        (direction = 'bullish' AND session_directional_bias >= 0.0
         AND symbol IN ('EURAUD','EURCAD','EURCHF','EURGBP','EURNZD')
         AND aoi_height_atr <= 1.3)
        OR
        (direction = 'bullish'
         AND symbol IN ('GBPAUD','GBPCAD','GBPCHF','GBPNZD')
         AND session_directional_bias >= 0.1)
        OR
        (direction = 'bullish' AND session_directional_bias >= 0.0
         AND symbol IN ('AUDCAD','AUDCHF','NZDCAD','NZDCHF'))
    )
    AND hour_of_day_utc NOT IN (17, 18, 19)
),
portfolio AS (
    SELECT * FROM gated
    WHERE
    -- Bear buckets
    (
        (symbol IN ('AUDJPY','CADJPY','CHFJPY','EURJPY','GBPJPY','NZDJPY','USDJPY') AND direction = 'bearish' AND htf_range_position_mid <= 0.25 AND sl_model = 'SL_ATR_0_5' AND hour_of_day_utc IN (6,7,8))
        OR (symbol IN ('AUDJPY','CADJPY','CHFJPY','EURJPY','GBPJPY','NZDJPY','USDJPY') AND direction = 'bearish' AND htf_range_position_mid >= 0.75 AND sl_model = 'SL_ATR_1_0' AND hour_of_day_utc IN (4,5,6,7,8))
        OR (symbol IN ('AUDUSD','EURUSD','GBPUSD','NZDUSD','USDCAD','USDCHF') AND direction = 'bearish' AND htf_range_position_mid <= 0.25 AND sl_model = 'SL_AOI_NEAR_PLUS_0_25' AND hour_of_day_utc IN (14,15,18))
        OR (symbol IN ('AUDUSD','EURUSD','GBPUSD','NZDUSD','USDCAD','USDCHF') AND direction = 'bearish' AND htf_range_position_mid >= 0.75 AND sl_model = 'SL_SIGNAL_CANDLE' AND hour_of_day_utc IN (1,16,17,18,19,20,21,22))
        OR (symbol IN ('EURAUD','EURCAD','EURCHF','EURGBP','EURNZD') AND direction = 'bearish' AND htf_range_position_mid <= 0.25 AND sl_model = 'SL_AOI_NEAR_PLUS_0_5' AND hour_of_day_utc IN (0,17,18,21,22,23))
        OR (symbol IN ('EURAUD','EURCAD','EURCHF','EURGBP','EURNZD') AND direction = 'bearish' AND htf_range_position_mid >= 0.75 AND sl_model = 'SL_AOI_FAR' AND hour_of_day_utc IN (1,2,3,4,5,6,7,8,9))
        OR (symbol IN ('GBPAUD','GBPCAD','GBPCHF','GBPNZD') AND direction = 'bearish' AND htf_range_position_mid <= 0.25 AND sl_model = 'SL_ATR_1_0' AND hour_of_day_utc IN (2,3,4,22,23))
        OR (symbol IN ('GBPAUD','GBPCAD','GBPCHF','GBPNZD') AND direction = 'bearish' AND htf_range_position_mid >= 0.75 AND sl_model = 'SL_ATR_0_5' AND hour_of_day_utc IN (0,16,17,18,19,22,23))
        OR (symbol IN ('AUDCAD','AUDCHF','NZDCAD','NZDCHF') AND direction = 'bearish' AND htf_range_position_mid <= 0.25 AND sl_model = 'SL_ATR_2_0' AND hour_of_day_utc IN (1,2,3,4,5,7,8,9))
        OR (symbol IN ('AUDCAD','AUDCHF','NZDCAD','NZDCHF') AND direction = 'bearish' AND htf_range_position_mid >= 0.75 AND sl_model = 'SL_ATR_0_5' AND hour_of_day_utc IN (0,1,3,4,5,18,19,20,21,22,23))
    )
    OR
    -- Bull buckets
    (
        (symbol IN ('AUDJPY','CADJPY','CHFJPY','EURJPY','GBPJPY','NZDJPY','USDJPY') AND direction = 'bullish' AND htf_range_position_mid <= 0.25 AND sl_model = 'SL_SIGNAL_CANDLE_PLUS_0_25' AND hour_of_day_utc IN (0,1,12,13,14))
        OR (symbol IN ('AUDJPY','CADJPY','CHFJPY','EURJPY','GBPJPY','NZDJPY','USDJPY') AND direction = 'bullish' AND htf_range_position_mid >= 0.75 AND sl_model = 'SL_AOI_NEAR_PLUS_0_25' AND hour_of_day_utc IN (4,5,6))
        OR (symbol IN ('AUDUSD','EURUSD','GBPUSD','NZDUSD','USDCAD','USDCHF') AND direction = 'bullish' AND htf_range_position_mid <= 0.25 AND sl_model = 'SL_SIGNAL_CANDLE' AND hour_of_day_utc IN (0,1,12,13,14,15))
        OR (symbol IN ('AUDUSD','EURUSD','GBPUSD','NZDUSD','USDCAD','USDCHF') AND direction = 'bullish' AND htf_range_position_mid >= 0.75 AND sl_model = 'SL_ATR_0_5' AND hour_of_day_utc IN (6,7,8))
        OR (symbol IN ('EURAUD','EURCAD','EURCHF','EURGBP','EURNZD') AND direction = 'bullish' AND htf_range_position_mid <= 0.25 AND sl_model = 'SL_ATR_1_5' AND hour_of_day_utc IN (0,1,3,4,5))
        OR (symbol IN ('EURAUD','EURCAD','EURCHF','EURGBP','EURNZD') AND direction = 'bullish' AND htf_range_position_mid >= 0.75 AND sl_model = 'SL_AOI_NEAR_PLUS_0_5' AND hour_of_day_utc IN (5,6,9))
        OR (symbol IN ('GBPAUD','GBPCAD','GBPCHF','GBPNZD') AND direction = 'bullish' AND htf_range_position_mid <= 0.25 AND sl_model = 'SL_SIGNAL_CANDLE_PLUS_0_25' AND hour_of_day_utc IN (0,1,5,6,7,8,9,10))
        OR (symbol IN ('GBPAUD','GBPCAD','GBPCHF','GBPNZD') AND direction = 'bullish' AND htf_range_position_mid >= 0.75 AND sl_model = 'SL_ATR_2_0' AND hour_of_day_utc IN (12,14,15))
        OR (symbol IN ('AUDCAD','AUDCHF','NZDCAD','NZDCHF') AND direction = 'bullish' AND htf_range_position_mid <= 0.25 AND sl_model = 'SL_ATR_1_0' AND hour_of_day_utc IN (0,1,2,3,4,5,6,21))
        OR (symbol IN ('AUDCAD','AUDCHF','NZDCAD','NZDCHF') AND direction = 'bullish' AND htf_range_position_mid >= 0.75 AND sl_model = 'SL_ATR_0_5' AND hour_of_day_utc IN (21,22,23))
    )
)
SELECT
    'Config #1: MILD bull + excl_h17-20' AS config,
    direction,
    COUNT(*) AS trades,
    ROUND(100.0 * SUM(CASE WHEN exit_reason = 'TP' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2) AS win_pct,
    ROUND(AVG(return_r)::numeric, 4) AS exp_r,
    ROUND(SUM(CASE WHEN return_r > 0 THEN return_r ELSE 0 END) /
          NULLIF(ABS(SUM(CASE WHEN return_r < 0 THEN return_r ELSE 0 END)), 0)::numeric, 3) AS pf
FROM portfolio
GROUP BY direction
ORDER BY direction;


-- ===========================
-- QUERY 6: Per-bucket breakdown for Config #1 (most detailed)
-- Shows which specific buckets have data in 2023
-- ===========================
WITH base AS (
    SELECT es.id, es.signal_time, es.symbol, es.direction, es.hour_of_day_utc,
        es.aoi_touch_count_since_creation,
        pec.htf_range_position_mid, pec.session_directional_bias,
        pec.aoi_height_atr, pec.distance_from_last_impulse_atr,
        sg.signal_candle_opposite_extreme_atr,
        esi.sl_model, esi.exit_reason, esi.return_r
    FROM trenda_replay.entry_signal es
    JOIN trenda_replay.pre_entry_context_v2 pec ON pec.entry_signal_id = es.id
    JOIN trenda_replay.sl_geometry_unbiased sg ON sg.entry_signal_id = es.id
    JOIN trenda_replay.exit_simulation_unbiased esi ON esi.entry_signal_id = es.id
    WHERE es.is_break_candle_last = TRUE
      AND es.sl_model_version = 'CHECK_GEO'
      AND esi.rr_multiple = 2.0
      AND EXTRACT(YEAR FROM es.signal_time) = 2023
),
gated AS (
    SELECT *,
        CASE
            WHEN symbol IN ('AUDJPY','CADJPY','CHFJPY','EURJPY','GBPJPY','NZDJPY','USDJPY') THEN 'jpy_pairs'
            WHEN symbol IN ('AUDUSD','EURUSD','GBPUSD','NZDUSD','USDCAD','USDCHF') THEN 'usd_majors'
            WHEN symbol IN ('EURAUD','EURCAD','EURCHF','EURGBP','EURNZD') THEN 'eur_crosses'
            WHEN symbol IN ('GBPAUD','GBPCAD','GBPCHF','GBPNZD') THEN 'gbp_crosses'
            WHEN symbol IN ('AUDCAD','AUDCHF','NZDCAD','NZDCHF') THEN 'commodity'
        END AS grp,
        CASE
            WHEN htf_range_position_mid >= 0.75 THEN 'premium'
            WHEN htf_range_position_mid <= 0.25 THEN 'discount'
            ELSE 'mid'
        END AS zone
    FROM base
    WHERE (
        (direction = 'bearish' AND aoi_touch_count_since_creation <= 3)
        OR
        (direction = 'bullish' AND session_directional_bias >= 0.0
         AND symbol IN ('AUDJPY','CADJPY','CHFJPY','EURJPY','GBPJPY','NZDJPY','USDJPY')
         AND signal_candle_opposite_extreme_atr <= 0.7)
        OR
        (direction = 'bullish'
         AND symbol IN ('AUDUSD','EURUSD','GBPUSD','NZDUSD','USDCAD','USDCHF')
         AND session_directional_bias >= 0.2)
        OR
        (direction = 'bullish' AND session_directional_bias >= 0.0
         AND symbol IN ('EURAUD','EURCAD','EURCHF','EURGBP','EURNZD')
         AND aoi_height_atr <= 1.3)
        OR
        (direction = 'bullish'
         AND symbol IN ('GBPAUD','GBPCAD','GBPCHF','GBPNZD')
         AND session_directional_bias >= 0.1)
        OR
        (direction = 'bullish' AND session_directional_bias >= 0.0
         AND symbol IN ('AUDCAD','AUDCHF','NZDCAD','NZDCHF'))
    )
    AND hour_of_day_utc NOT IN (17, 18, 19)
)
SELECT
    grp,
    direction,
    zone,
    sl_model,
    COUNT(*) AS trades,
    ROUND(100.0 * SUM(CASE WHEN exit_reason = 'TP' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2) AS win_pct,
    ROUND(AVG(return_r)::numeric, 4) AS exp_r,
    ROUND(SUM(CASE WHEN return_r > 0 THEN return_r ELSE 0 END) /
          NULLIF(ABS(SUM(CASE WHEN return_r < 0 THEN return_r ELSE 0 END)), 0)::numeric, 3) AS pf
FROM gated
GROUP BY grp, direction, zone, sl_model
HAVING COUNT(*) >= 5
ORDER BY grp, direction, zone;


-- ===========================
-- QUERY 7: Quick pass/fail summary — expected vs actual
-- Run this AFTER the others to compare
-- ===========================
-- Expected from 2019-2025 (excl 2023) performance:
--   Config #1: ~84 trades/year, ~52% win, exp ~0.58, MLS ~7
--   Config #2: ~97 trades/year, ~50% win, exp ~0.51, MLS ~7
--   Config #3: ~94 trades/year, ~53% win, exp ~0.59, MLS ~8
--
-- PASS criteria (2023 holdout):
--   - Win% within ±8% of training average (44-60% for #1)
--   - Expectancy R > 0 (profitable)
--   - Trade count within ±40% of yearly average
--   - Profit factor > 1.0
