-- Migration: Add AOI Geometry Metrics to Pre-Entry Context V2

ALTER TABLE trenda_replay.pre_entry_context_v2
ADD COLUMN IF NOT EXISTS aoi_height_atr NUMERIC,
ADD COLUMN IF NOT EXISTS aoi_entry_depth NUMERIC,
ADD COLUMN IF NOT EXISTS aoi_compression_ratio NUMERIC;
