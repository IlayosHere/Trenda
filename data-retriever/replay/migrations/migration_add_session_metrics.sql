-- Migration: Add Session Dynamics Metrics to Pre-Entry Context V2

ALTER TABLE trenda_replay.pre_entry_context_v2
ADD COLUMN IF NOT EXISTS session_transition_prox_flag BOOLEAN, --checked
ADD COLUMN IF NOT EXISTS session_align_break_4h BOOLEAN, --checked
ADD COLUMN IF NOT EXISTS session_align_break_1d BOOLEAN, --checked
ADD COLUMN IF NOT EXISTS session_align_break_1w BOOLEAN; --checked
