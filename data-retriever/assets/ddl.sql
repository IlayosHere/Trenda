CREATE TABLE IF NOT EXISTS fordash.forex (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

-- 2. Create the lookup table for timeframes
CREATE TABLE IF NOT EXISTS fordash.timeframes (
    id SERIAL PRIMARY KEY,
    type TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS fordash.aoi_type (
    id SERIAL PRIMARY KEY,
    type TEXT NOT NULL UNIQUE
);

-- 3. Create the main data table with foreign keys
CREATE TABLE IF NOT EXISTS fordash.trend_data (
    forex_id INTEGER NOT NULL REFERENCES fordash.forex(id) ON DELETE CASCADE,    
    timeframe_id INTEGER NOT NULL REFERENCES fordash.timeframes(id) ON DELETE CASCADE,    
    trend TEXT,
    high REAL,
    low REAL,    
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(forex_id, timeframe_id)
);

CREATE TABLE IF NOT EXISTS fordash.area_of_interest (
    id SERIAL,
    forex_id INTEGER NOT NULL REFERENCES fordash.forex(id) ON DELETE CASCADE,    
    timeframe_id INTEGER NOT NULL REFERENCES fordash.timeframes(id) ON DELETE CASCADE,    
    lower_bound REAL,
    upper_bound REAL,    
    type_id INTEGER NOT NULL REFERENCES fordash.aoi_type(id) ON DELETE CASCADE,    
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);