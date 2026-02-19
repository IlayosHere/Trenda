-- Add MAE and MFE columns to checkpoint_return table
-- These metrics track the Maximum Adverse/Favorable Excursion (in ATR)
-- experienced up to the checkpoint bar.

ALTER TABLE trenda_replay.checkpoint_return 
ADD COLUMN IF NOT EXISTS mae_atr NUMERIC,
ADD COLUMN IF NOT EXISTS mfe_atr NUMERIC;

COMMENT ON COLUMN trenda_replay.checkpoint_return.mae_atr IS 'Maximum Adverse Excursion (in ATR) up to this checkpoint';
COMMENT ON COLUMN trenda_replay.checkpoint_return.mfe_atr IS 'Maximum Favorable Excursion (in ATR) up to this checkpoint';
