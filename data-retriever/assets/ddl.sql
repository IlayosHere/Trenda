CREATE TABLE IF NOT EXISTS forex (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

-- 2. Create the lookup table for timeframes
CREATE TABLE IF NOT EXISTS timeframes (
    id SERIAL PRIMARY KEY,
    type TEXT NOT NULL UNIQUE
);

-- 3. Create the main data table with foreign keys
CREATE TABLE IF NOT EXISTS trend_data (
    forex_id INTEGER NOT NULL REFERENCES forex(id) ON DELETE CASCADE,    
    timeframe_id INTEGER NOT NULL REFERENCES timeframes(id) ON DELETE CASCADE,    
    trend TEXT,
    high REAL,
    low REAL,    
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(forex_id, timeframe_id)
);

CREATE TABLE IF NOT EXISTS area_of_interest (
    id SERIAL,
    forex_id INTEGER NOT NULL REFERENCES forex(id) ON DELETE CASCADE,    
    timeframe_id INTEGER NOT NULL REFERENCES timeframes(id) ON DELETE CASCADE,    
    lower_bound REAL,
    upper_bound REAL,    
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(forex_id, timeframe_id)
);