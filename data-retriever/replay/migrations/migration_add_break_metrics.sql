-- Migration: Add Break and After-Break Metrics to Pre-Entry Context V2

ALTER TABLE trenda_replay.pre_entry_context_v2
ADD COLUMN IF NOT EXISTS break_def_dist_from_balance_atr NUMERIC,
ADD COLUMN IF NOT EXISTS break_def_liquidity_sweep BOOLEAN,

ADD COLUMN IF NOT EXISTS after_break_pullback_depth_atr NUMERIC,
ADD COLUMN IF NOT EXISTS after_break_close_dist_edge_atr NUMERIC,
ADD COLUMN IF NOT EXISTS after_break_range_compress_ratio NUMERIC,
ADD COLUMN IF NOT EXISTS after_break_retest_fail_flag BOOLEAN;
