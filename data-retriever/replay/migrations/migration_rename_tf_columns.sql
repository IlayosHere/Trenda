-- =============================================================================
-- Migration: Rename TF-specific columns to generic role-based names (low/mid/high)
-- Prepares the schema for configurable timeframe profiles.
-- =============================================================================

BEGIN;

-- =============================================================================
-- 1. entry_signal: Rename trend columns + add profile flag
-- =============================================================================
ALTER TABLE trenda_replay.entry_signal
    RENAME COLUMN trend_4h TO trend_low;

ALTER TABLE trenda_replay.entry_signal
    RENAME COLUMN trend_1d TO trend_mid;

ALTER TABLE trenda_replay.entry_signal
    RENAME COLUMN trend_1w TO trend_high;

ALTER TABLE trenda_replay.entry_signal
    ADD COLUMN IF NOT EXISTS timeframe_profile VARCHAR(20) DEFAULT 'DEFAULT';

-- Backfill the new column for existing rows
UPDATE trenda_replay.entry_signal
SET timeframe_profile = 'DEFAULT'
WHERE timeframe_profile IS NULL;

-- =============================================================================
-- 2. pre_entry_context_v2: Rename HTF Range Position columns
-- =============================================================================
ALTER TABLE trenda_replay.pre_entry_context_v2
    RENAME COLUMN htf_range_position_daily TO htf_range_position_mid;

ALTER TABLE trenda_replay.pre_entry_context_v2
    RENAME COLUMN htf_range_position_weekly TO htf_range_position_high;

-- =============================================================================
-- 3. pre_entry_context_v2: Rename Distance to HTF Boundary columns
-- =============================================================================
ALTER TABLE trenda_replay.pre_entry_context_v2
    RENAME COLUMN distance_to_daily_high_atr TO distance_to_mid_tf_high_atr;

ALTER TABLE trenda_replay.pre_entry_context_v2
    RENAME COLUMN distance_to_daily_low_atr TO distance_to_mid_tf_low_atr;

ALTER TABLE trenda_replay.pre_entry_context_v2
    RENAME COLUMN distance_to_weekly_high_atr TO distance_to_high_tf_high_atr;

ALTER TABLE trenda_replay.pre_entry_context_v2
    RENAME COLUMN distance_to_weekly_low_atr TO distance_to_high_tf_low_atr;

ALTER TABLE trenda_replay.pre_entry_context_v2
    RENAME COLUMN distance_to_4h_high_atr TO distance_to_low_tf_high_atr;

ALTER TABLE trenda_replay.pre_entry_context_v2
    RENAME COLUMN distance_to_4h_low_atr TO distance_to_low_tf_low_atr;

-- =============================================================================
-- 4. pre_entry_context_v2: Rename HTF Range Size columns
-- =============================================================================
ALTER TABLE trenda_replay.pre_entry_context_v2
    RENAME COLUMN htf_range_size_daily_atr TO htf_range_size_mid_atr;

ALTER TABLE trenda_replay.pre_entry_context_v2
    RENAME COLUMN htf_range_size_weekly_atr TO htf_range_size_high_atr;

-- =============================================================================
-- 5. pre_entry_context_v2: Rename AOI Midpoint Range Position columns
-- =============================================================================
ALTER TABLE trenda_replay.pre_entry_context_v2
    RENAME COLUMN aoi_midpoint_range_position_daily TO aoi_midpoint_range_position_mid;

ALTER TABLE trenda_replay.pre_entry_context_v2
    RENAME COLUMN aoi_midpoint_range_position_weekly TO aoi_midpoint_range_position_high;

-- =============================================================================
-- 6. pre_entry_context_v2: Rename HTF Trend Quality Metrics (9 columns)
-- =============================================================================
-- Slope Strength
ALTER TABLE trenda_replay.pre_entry_context_v2
    RENAME COLUMN htf_slope_strength_4h TO htf_slope_strength_low;

ALTER TABLE trenda_replay.pre_entry_context_v2
    RENAME COLUMN htf_slope_strength_1d TO htf_slope_strength_mid;

ALTER TABLE trenda_replay.pre_entry_context_v2
    RENAME COLUMN htf_slope_strength_1w TO htf_slope_strength_high;

-- Impulse Ratio
ALTER TABLE trenda_replay.pre_entry_context_v2
    RENAME COLUMN htf_impulse_ratio_4h TO htf_impulse_ratio_low;

ALTER TABLE trenda_replay.pre_entry_context_v2
    RENAME COLUMN htf_impulse_ratio_1d TO htf_impulse_ratio_mid;

ALTER TABLE trenda_replay.pre_entry_context_v2
    RENAME COLUMN htf_impulse_ratio_1w TO htf_impulse_ratio_high;

-- Structural Efficiency
ALTER TABLE trenda_replay.pre_entry_context_v2
    RENAME COLUMN htf_struct_eff_4h TO htf_struct_eff_low;

ALTER TABLE trenda_replay.pre_entry_context_v2
    RENAME COLUMN htf_struct_eff_1d TO htf_struct_eff_mid;

ALTER TABLE trenda_replay.pre_entry_context_v2
    RENAME COLUMN htf_struct_eff_1w TO htf_struct_eff_high;

-- =============================================================================
-- 7. pre_entry_context_v2: Rename Session Alignment columns
-- =============================================================================
ALTER TABLE trenda_replay.pre_entry_context_v2
    RENAME COLUMN session_align_break_4h TO session_align_break_low;

ALTER TABLE trenda_replay.pre_entry_context_v2
    RENAME COLUMN session_align_break_1d TO session_align_break_mid;

ALTER TABLE trenda_replay.pre_entry_context_v2
    RENAME COLUMN session_align_break_1w TO session_align_break_high;

-- =============================================================================
-- 8. pre_entry_context_v2: Rename HTF Structure Obstacle Distance columns
-- =============================================================================
ALTER TABLE trenda_replay.pre_entry_context_v2
    RENAME COLUMN distance_to_4h_struct_high_atr TO distance_to_low_tf_struct_high_atr;

ALTER TABLE trenda_replay.pre_entry_context_v2
    RENAME COLUMN distance_to_4h_struct_low_atr TO distance_to_low_tf_struct_low_atr;

ALTER TABLE trenda_replay.pre_entry_context_v2
    RENAME COLUMN distance_to_daily_struct_high_atr TO distance_to_mid_tf_struct_high_atr;

ALTER TABLE trenda_replay.pre_entry_context_v2
    RENAME COLUMN distance_to_daily_struct_low_atr TO distance_to_mid_tf_struct_low_atr;

ALTER TABLE trenda_replay.pre_entry_context_v2
    RENAME COLUMN distance_to_weekly_struct_high_atr TO distance_to_high_tf_struct_high_atr;

ALTER TABLE trenda_replay.pre_entry_context_v2
    RENAME COLUMN distance_to_weekly_struct_low_atr TO distance_to_high_tf_struct_low_atr;

COMMIT;

-- =============================================================================
-- Verification: Check column names after migration
-- =============================================================================
-- SELECT column_name FROM information_schema.columns
-- WHERE table_schema = 'trenda_replay' AND table_name = 'entry_signal'
-- ORDER BY ordinal_position;
--
-- SELECT column_name FROM information_schema.columns
-- WHERE table_schema = 'trenda_replay' AND table_name = 'pre_entry_context_v2'
-- ORDER BY ordinal_position;
