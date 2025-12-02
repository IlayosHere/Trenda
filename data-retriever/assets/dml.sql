INSERT INTO trenda.forex (name) VALUES
('EURUSD'),
('GBPUSD'),
('USDJPY'),
('USDCHF'),
('USDCAD'),
('AUDUSD'),
('NZDUSD'),
('GBPCAD'),
('EURJPY'),
('GBPJPY'),
('AUDJPY'),
('CADJPY'),
('NZDJPY'),
('CHFJPY'),
('EURAUD'),
('EURNZD'),
('EURGBP'),
('EURCHF'),
('GBPAUD'),
('GBPNZD'),
('AUDNZD'),
('AUDCAD'),
('NZDCAD')
ON CONFLICT (name) DO NOTHING;

-- DML for populating the 'timeframes' table
INSERT INTO trenda.timeframes (type) VALUES
('1W'),
('1D'),
('4H'),
('1H')
ON CONFLICT (type) DO NOTHING;

INSERT INTO trenda.aoi_type (type) VALUES
('tradable'),
('reference')
ON CONFLICT (type) DO NOTHING;
