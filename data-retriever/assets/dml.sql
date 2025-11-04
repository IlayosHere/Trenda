INSERT INTO fordash.forex (name) VALUES
('EURUSD'),
('GBPUSD'),
('USDJPY'),
('USDCHF'),
('USDCAD'),
('AUDUSD'),
('NZDUSD'),
('GBPCAD'),
('EURJPY'),
('XAUUSD')
ON CONFLICT (name) DO NOTHING;

-- DML for populating the 'timeframes' table
INSERT INTO fordash.timeframes (type) VALUES
('1D'),
('4H'),
('1H'),
('15min')
ON CONFLICT (type) DO NOTHING;
