CREATE SCHEMA IF NOT EXISTS trenda;

CREATE TABLE IF NOT EXISTS trenda.forex (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

-- Lookup table for timeframes
CREATE TABLE IF NOT EXISTS trenda.timeframes (
    id SERIAL PRIMARY KEY,
    type TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS trenda.aoi_type (
    id SERIAL PRIMARY KEY,
    type TEXT NOT NULL UNIQUE
);

-- Main trend data table with foreign keys
CREATE TABLE IF NOT EXISTS trenda.trend_data (
    forex_id INTEGER NOT NULL REFERENCES trenda.forex(id) ON DELETE CASCADE,
    timeframe_id INTEGER NOT NULL REFERENCES trenda.timeframes(id) ON DELETE CASCADE,
    trend TEXT,
    high REAL,
    low REAL,
    last_updated TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(forex_id, timeframe_id)
);

CREATE TABLE IF NOT EXISTS trenda.area_of_interest (
    id SERIAL,
    forex_id INTEGER NOT NULL REFERENCES trenda.forex(id) ON DELETE CASCADE,
    timeframe_id INTEGER NOT NULL REFERENCES trenda.timeframes(id) ON DELETE CASCADE,
    lower_bound REAL,
    upper_bound REAL,
    type_id INTEGER NOT NULL REFERENCES trenda.aoi_type(id) ON DELETE CASCADE,
    last_updated TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Entry signal storage
CREATE TABLE IF NOT EXISTS trenda.entry_signal (
    id SERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    signal_time TIMESTAMPTZ NOT NULL,
    trend TEXT NOT NULL,
    aoi_high REAL NOT NULL,
    aoi_low REAL NOT NULL,
    is_success BOOLEAN
);

CREATE TABLE IF NOT EXISTS trenda.entry_signal_cnadles (
    entry_signal_id INTEGER NOT NULL REFERENCES trenda.entry_signal(id) ON DELETE CASCADE,
    cnalde_number INTEGER NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    open REAL NOT NULL,
    close REAL NOT NULL,
    PRIMARY KEY (entry_signal_id, cnalde_number)
);
