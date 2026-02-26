-- Migration: delayed_entry_outcome
-- Run once against trenda_replay schema before backfill.

CREATE TABLE IF NOT EXISTS trenda_replay.delayed_entry_outcome (
    id                  SERIAL          PRIMARY KEY,
    entry_signal_id     INTEGER         NOT NULL
                            REFERENCES trenda_replay.entry_signal(id),
    delay_bars          SMALLINT        NOT NULL,           -- 3 or 6
    sl_model            VARCHAR(40)     NOT NULL,
    rr_multiple         NUMERIC(4,2)    NOT NULL,
    delay_return_atr    NUMERIC(10,4)   NOT NULL,           -- ATR return at delay bar (favorable-signed)
    sl_dist_atr         NUMERIC(10,4)   NOT NULL,           -- SL distance from delay bar close (ATR)
    exit_reason         VARCHAR(10)     NOT NULL,           -- 'TP', 'SL', 'TIMEOUT'
    bars_to_exit        SMALLINT        NOT NULL,           -- bars from delay entry to exit
    return_r            NUMERIC(10,4)   NOT NULL,           -- return in R (+rr, -1.0, or partial)
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    UNIQUE (entry_signal_id, delay_bars, sl_model, rr_multiple)
);

CREATE INDEX IF NOT EXISTS idx_deo_signal_id
    ON trenda_replay.delayed_entry_outcome (entry_signal_id);

CREATE INDEX IF NOT EXISTS idx_deo_delay_sl_rr
    ON trenda_replay.delayed_entry_outcome (delay_bars, sl_model, rr_multiple);
