-- Query 6: Trader Performance by Seniority Band
-- ========================================
-- Classify active traders into seniority bands based on years of service
-- as of end of Q1 (2024-03-31), then compute per-band aggregates:
-- number of traders, average P&L per trader, and total settled trades.
--
-- Seniority: Junior (<3 years), Mid (3-7 inclusive), Senior (>7 years)
--
-- Expected output columns: seniority, trader_count, avg_pnl_per_trader, total_trades
-- Ordered by: Senior first, then Mid, then Junior

SELECT
    CASE
        WHEN (julianday('now') - julianday(t.hire_date)) / 365.25 < 3 THEN 'Junior'
        WHEN (julianday('now') - julianday(t.hire_date)) / 365.25 <= 7 THEN 'Mid'
        ELSE 'Senior'
    END AS seniority,
    COUNT(DISTINCT t.id) AS trader_count,
    ROUND(AVG(tr.quantity * tr.price * CASE tr.direction
        WHEN 'BUY' THEN -1 WHEN 'SELL' THEN 1 END
        - tr.commission), 2) AS avg_pnl_per_trader,
    COUNT(tr.id) AS total_trades
FROM traders t
JOIN trades tr ON t.id = tr.trader_id
WHERE tr.trade_date BETWEEN '2024-01-01' AND '2024-03-31'
GROUP BY seniority
ORDER BY CASE seniority WHEN 'Senior' THEN 1 WHEN 'Mid' THEN 2 ELSE 3 END;
