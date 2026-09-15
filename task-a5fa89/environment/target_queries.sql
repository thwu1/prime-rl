-- Target Compliance Queries
-- Design indexes so none of these queries perform full table scans
-- on the trades (2000 rows) or compliance_flags (300 rows) tables.
-- Maximum 4 user-created indexes allowed.

-- Q1: Trades by specific trader in date range
SELECT id, instrument_id, side, quantity, price
FROM trades
WHERE trader_id = 7
  AND trade_date BETWEEN '2024-03-01' AND '2024-06-30';

-- Q2: Large trades for a specific instrument
SELECT id, trader_id, side, quantity, trade_date
FROM trades
WHERE instrument_id = 5
  AND price > 500.0;

-- Q3: Critical unresolved flags with trade details
SELECT compliance_flags.id, compliance_flags.flag_type,
       compliance_flags.severity, trades.price, trades.quantity
FROM compliance_flags
JOIN trades ON compliance_flags.trade_id = trades.id
WHERE compliance_flags.severity = 'CRITICAL'
  AND compliance_flags.resolved = 0;

-- Q4: Recent trades sorted by date
SELECT id, trader_id, instrument_id, side, quantity, price
FROM trades
WHERE trade_date >= '2024-11-01'
ORDER BY trade_date;

-- Q5: Volume by trader for a specific instrument
SELECT trader_id, side, SUM(quantity) AS total_qty, COUNT(*) AS num_trades
FROM trades
WHERE instrument_id = 15
GROUP BY trader_id, side
ORDER BY total_qty DESC;
