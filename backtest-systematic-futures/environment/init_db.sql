SELECT setseed(0.42);

CREATE TABLE daily_prices (
    symbol VARCHAR NOT NULL,
    date DATE NOT NULL,
    price DOUBLE NOT NULL,
    volume INTEGER,
    open_interest INTEGER,
    PRIMARY KEY(symbol, date)
);

INSERT INTO daily_prices
SELECT 'SP500' AS symbol,
       date,
       price,
       (random() * 195000 + 5000)::INTEGER AS volume,
       (random() * 450000 + 50000)::INTEGER AS open_interest
FROM read_csv('/tmp/data/SP500.csv');

INSERT INTO daily_prices
SELECT 'EUROSTOXX' AS symbol,
       date,
       price,
       (random() * 195000 + 5000)::INTEGER AS volume,
       (random() * 450000 + 50000)::INTEGER AS open_interest
FROM read_csv('/tmp/data/EUROSTOXX.csv');

INSERT INTO daily_prices
SELECT 'US10' AS symbol,
       date,
       price,
       (random() * 195000 + 5000)::INTEGER AS volume,
       (random() * 450000 + 50000)::INTEGER AS open_interest
FROM read_csv('/tmp/data/US10.csv');

INSERT INTO daily_prices
SELECT 'GOLD' AS symbol,
       date,
       price,
       (random() * 195000 + 5000)::INTEGER AS volume,
       (random() * 450000 + 50000)::INTEGER AS open_interest
FROM read_csv('/tmp/data/GOLD.csv');

CREATE VIEW price_summary AS
SELECT symbol,
       MIN(date) AS first_date,
       MAX(date) AS last_date,
       COUNT(*) AS num_rows,
       ROUND(AVG(price), 2) AS avg_price
FROM daily_prices
GROUP BY symbol
ORDER BY symbol;

COPY (
  SELECT * FROM (VALUES
    ('EUROSTOXX', 10.0, 0.25),
    ('GOLD', 100.0, 0.20),
    ('SP500', 50.0, 0.30),
    ('US10', 1000.0, 0.25)
  ) AS t(symbol, point_size, weight)
) TO '/app/instruments.parquet' (FORMAT PARQUET);

COPY (
  SELECT * FROM (VALUES
    ('EUROSTOXX', 'ewmac8_32', 0.333),
    ('EUROSTOXX', 'ewmac16_64', 0.334),
    ('EUROSTOXX', 'ewmac32_128', 0.333),
    ('GOLD', 'ewmac8_32', 0.333),
    ('GOLD', 'ewmac16_64', 0.334),
    ('GOLD', 'ewmac32_128', 0.333),
    ('SP500', 'ewmac8_32', 0.333),
    ('SP500', 'ewmac16_64', 0.334),
    ('SP500', 'ewmac32_128', 0.333),
    ('US10', 'ewmac8_32', 0.333),
    ('US10', 'ewmac16_64', 0.334),
    ('US10', 'ewmac32_128', 0.333)
  ) AS t(symbol, rule_name, weight)
) TO '/app/forecast_weights.parquet' (FORMAT PARQUET);
