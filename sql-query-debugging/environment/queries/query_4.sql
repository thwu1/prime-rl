-- Query 4: Risk Utilization Report
-- ========================================
-- Show the risk utilization percentage for each active trader's
-- asset class, using the most recently effective and non-expired
-- risk limit as of 2024-03-31.
--
-- risk_utilization_pct = |net_position| / max_position * 100
--
-- Expected output columns: name, desk, asset_class, max_position,
--                          net_position, utilization_pct
-- Ordered by: utilization_pct DESC
-- net_position is based only on settled trades.

SELECT
    t.name,
    t.desk,
    rl.asset_class,
    rl.max_position,
    SUM(tr.quantity * CASE tr.direction WHEN 'BUY' THEN 1 ELSE -1 END) AS net_position,
    ROUND(SUM(tr.quantity * CASE tr.direction WHEN 'BUY' THEN 1 ELSE -1 END)
          * 100.0 / rl.max_position, 2) AS utilization_pct
FROM traders t
JOIN risk_limits rl ON t.id = rl.trader_id
JOIN trades tr ON t.id = tr.trader_id
JOIN instruments i ON tr.instrument_id = i.id AND i.asset_class = rl.asset_class
WHERE t.is_active = 1
GROUP BY t.id, t.name, t.desk, rl.asset_class
ORDER BY utilization_pct DESC;
