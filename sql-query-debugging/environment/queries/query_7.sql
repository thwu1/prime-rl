-- Query 7: End-of-Quarter Position Valuation
-- ========================================
-- For each active trader, show their net position per instrument valued
-- at the latest available closing price. Include total commissions paid.
--
-- Expected output columns: name, symbol, position, market_value, total_commission
-- Ordered by: name ASC, symbol ASC
-- Only include trader-instrument pairs where net position is non-zero.
-- Net position: BUY = +1, SELL = -1

SELECT
    t.name,
    i.symbol,
    SUM(tr.quantity * CASE tr.direction WHEN 'BUY' THEN 1 WHEN 'SELL' THEN -1 END) AS position,
    ROUND(SUM(tr.quantity * CASE tr.direction WHEN 'BUY' THEN 1 WHEN 'SELL' THEN -1 END)
          * dp.close_price, 2) AS market_value,
    ROUND(SUM(tr.commission), 2) AS total_commission
FROM traders t
JOIN trades tr ON t.id = tr.trader_id
JOIN instruments i ON tr.instrument_id = i.id
JOIN daily_prices dp ON i.id = dp.instrument_id
    AND dp.price_date = (SELECT MAX(price_date) FROM daily_prices WHERE instrument_id = i.id)
GROUP BY t.name, i.symbol, dp.close_price
HAVING position != 0
ORDER BY t.name, i.symbol;
