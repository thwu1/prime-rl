CREATE TABLE source_instruments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT NOT NULL,
    instrument TEXT NOT NULL,
    registered_at TEXT NOT NULL DEFAULT '2023-12-01'
);

CREATE UNIQUE INDEX idx_source_instrument ON source_instruments(source_name, instrument);

INSERT INTO source_instruments (source_name, instrument) VALUES ('alpha', 'AAPL');
INSERT INTO source_instruments (source_name, instrument) VALUES ('alpha', 'GOOGL');
INSERT INTO source_instruments (source_name, instrument) VALUES ('alpha', 'MSFT ');

INSERT INTO source_instruments (source_name, instrument) VALUES ('beta', 'AAPL');
INSERT INTO source_instruments (source_name, instrument) VALUES ('beta', 'MSFT');
INSERT INTO source_instruments (source_name, instrument) VALUES ('beta', 'TSLA ');

INSERT INTO source_instruments (source_name, instrument) VALUES ('gamma', 'GOOGL');
INSERT INTO source_instruments (source_name, instrument) VALUES ('gamma', 'TSLA');
INSERT INTO source_instruments (source_name, instrument) VALUES ('gamma', 'AMZN');

INSERT INTO source_instruments (source_name, instrument) VALUES ('delta', 'NFLX');
INSERT INTO source_instruments (source_name, instrument) VALUES ('delta', '0050');
INSERT INTO source_instruments (source_name, instrument) VALUES ('delta', 'AMZN');

INSERT INTO source_instruments (source_name, instrument) VALUES ('epsilon', 'MSFT');
INSERT INTO source_instruments (source_name, instrument) VALUES ('epsilon', 'TSLA');
INSERT INTO source_instruments (source_name, instrument) VALUES ('epsilon', 'NFLX');
