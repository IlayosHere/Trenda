-- Migration: Add HTF Trend Quality Metrics to Pre-Entry Context V2

ALTER TABLE trenda_replay.pre_entry_context_v2
ADD COLUMN IF NOT EXISTS htf_slope_strength_4h NUMERIC,
ADD COLUMN IF NOT EXISTS htf_slope_strength_1d NUMERIC,
ADD COLUMN IF NOT EXISTS htf_slope_strength_1w NUMERIC,

ADD COLUMN IF NOT EXISTS htf_impulse_ratio_4h NUMERIC,
ADD COLUMN IF NOT EXISTS htf_impulse_ratio_1d NUMERIC,
ADD COLUMN IF NOT EXISTS htf_impulse_ratio_1w NUMERIC,

ADD COLUMN IF NOT EXISTS htf_struct_eff_4h NUMERIC,
ADD COLUMN IF NOT EXISTS htf_struct_eff_1d NUMERIC,
ADD COLUMN IF NOT EXISTS htf_struct_eff_1w NUMERIC;
