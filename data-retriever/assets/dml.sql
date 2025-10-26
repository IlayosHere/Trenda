INSERT INTO trenda.forex (name) VALUES
('EURUSD'),
('GBPUSD'),
('USDJPY'),
('USDCHF'),
('USDCAD'),
('AUDUSD'),
('NZDUSD'),
('GBPCAD'),
('EURJPY')
ON CONFLICT (name) DO NOTHING;

-- DML for populating the 'timeframes' table
INSERT INTO trenda.timeframes (type) VALUES
('1W'),
('1D'),
('4H'),
('1H'),
('30min'),
('15min')
ON CONFLICT (type) DO NOTHING;
