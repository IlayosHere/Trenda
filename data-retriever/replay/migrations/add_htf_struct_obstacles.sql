-- Migration: Add HTF structure-based obstacle distance columns
-- Run this BEFORE running backfill_htf_struct_obstacles.py

-- Add new columns for trend-based HTF obstacle distances
ALTER TABLE trenda_replay.pre_entry_context_v2 
ADD COLUMN IF NOT EXISTS distance_to_4h_struct_high_atr NUMERIC,
ADD COLUMN IF NOT EXISTS distance_to_4h_struct_low_atr NUMERIC,
ADD COLUMN IF NOT EXISTS distance_to_daily_struct_high_atr NUMERIC,
ADD COLUMN IF NOT EXISTS distance_to_daily_struct_low_atr NUMERIC,
ADD COLUMN IF NOT EXISTS distance_to_weekly_struct_high_atr NUMERIC,
ADD COLUMN IF NOT EXISTS distance_to_weekly_struct_low_atr NUMERIC,
ADD COLUMN IF NOT EXISTS distance_to_next_htf_struct_obstacle_atr NUMERIC;

-- Add comments for clarity
COMMENT ON COLUMN trenda_replay.pre_entry_context_v2.distance_to_4h_struct_high_atr IS 'Distance from entry to 4H trend structure high in ATR units';
COMMENT ON COLUMN trenda_replay.pre_entry_context_v2.distance_to_4h_struct_low_atr IS 'Distance from entry to 4H trend structure low in ATR units';
COMMENT ON COLUMN trenda_replay.pre_entry_context_v2.distance_to_daily_struct_high_atr IS 'Distance from entry to 1D trend structure high in ATR units';
COMMENT ON COLUMN trenda_replay.pre_entry_context_v2.distance_to_daily_struct_low_atr IS 'Distance from entry to 1D trend structure low in ATR units';
COMMENT ON COLUMN trenda_replay.pre_entry_context_v2.distance_to_weekly_struct_high_atr IS 'Distance from entry to 1W trend structure high in ATR units';
COMMENT ON COLUMN trenda_replay.pre_entry_context_v2.distance_to_weekly_struct_low_atr IS 'Distance from entry to 1W trend structure low in ATR units';
COMMENT ON COLUMN trenda_replay.pre_entry_context_v2.distance_to_next_htf_struct_obstacle_atr IS 'Min distance to nearest HTF structure level in trade direction (ATR)';
