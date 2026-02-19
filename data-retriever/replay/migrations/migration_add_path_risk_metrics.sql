-- Migration: Add Path-Risk Context Metrics to Pre-Entry Context V2

ALTER TABLE trenda_replay.pre_entry_context_v2
ADD COLUMN IF NOT EXISTS dist_nearest_opposing_liq_atr NUMERIC,
ADD COLUMN IF NOT EXISTS structure_density_behind_entry NUMERIC;
