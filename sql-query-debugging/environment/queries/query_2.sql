-- Query 2: Settlement Anomaly Detection
-- ========================================
-- Identify trades where the actual settlement date differs from the
-- expected T+2 date. T+2 means two business days after the trade date,
-- skipping weekends (Saturday and Sunday).
--
-- Expected output columns: trade_id, trader_name, symbol, trade_date,
--                          settlement_date, expected_settlement
-- Ordered by: trade_date ASC
-- Should only include actual anomalies (mismatched settlements).

SELECT
    tr.id AS trade_id,
    t.name AS trader_name,
    i.symbol,
    tr.trade_date,
    tr.settlement_date,
    DATE(tr.trade_date, '+2 days') AS expected_settlement
FROM trades tr
JOIN traders t ON tr.trader_id = t.id
JOIN instruments i ON tr.instrument_id = i.id
WHERE tr.settlement_date <> DATE(tr.trade_date, '+2 days')
   OR tr.settlement_date IS NULL
ORDER BY tr.trade_date;
