-- =============================================================================
-- Migration: Add bias verification columns to entry_signal
-- =============================================================================
-- These columns store the "real" (unbiased) trend data computed after fixing
-- the HTF candle alignment bug in get_candles_up_to.
--
-- Usage:
--   psql -d trenda -f add_bias_verification_columns.sql
-- =============================================================================

-- Add columns for bias-free trend data
ALTER TABLE trenda_replay.entry_signal
    ADD COLUMN IF NOT EXISTS real_trend_4h VARCHAR(10),
    ADD COLUMN IF NOT EXISTS real_trend_1d VARCHAR(10),
    ADD COLUMN IF NOT EXISTS real_trend_1w VARCHAR(10),
    ADD COLUMN IF NOT EXISTS real_overall_trend VARCHAR(10),
    ADD COLUMN IF NOT EXISTS real_trend_alignment INTEGER,
    ADD COLUMN IF NOT EXISTS aoi_still_valid BOOLEAN,
    ADD COLUMN IF NOT EXISTS trend_matches_original BOOLEAN;

-- Index for finding signals that need backfill
CREATE INDEX IF NOT EXISTS idx_entry_signal_needs_backfill 
ON trenda_replay.entry_signal (sl_model_version, signal_time)
WHERE real_trend_4h IS NULL;

-- Comment on columns
COMMENT ON COLUMN trenda_replay.entry_signal.real_trend_4h IS 'Unbiased 4H trend (computed with fixed HTF alignment)';
COMMENT ON COLUMN trenda_replay.entry_signal.real_trend_1d IS 'Unbiased 1D trend (computed with fixed HTF alignment)';
COMMENT ON COLUMN trenda_replay.entry_signal.real_trend_1w IS 'Unbiased 1W trend (computed with fixed HTF alignment)';
COMMENT ON COLUMN trenda_replay.entry_signal.real_overall_trend IS 'Overall trend using 2-aligned-TF logic (bullish/bearish/neutral)';
COMMENT ON COLUMN trenda_replay.entry_signal.real_trend_alignment IS 'Unbiased trend alignment strength';
COMMENT ON COLUMN trenda_replay.entry_signal.aoi_still_valid IS 'TRUE if AOI zone still generated without bias';
COMMENT ON COLUMN trenda_replay.entry_signal.trend_matches_original IS 'TRUE if all 3 real trends match original biased trends';
