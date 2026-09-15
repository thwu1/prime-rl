-- Query 1: Desk P&L Summary for Q1 2024
-- ========================================
-- Compute the total profit/loss for each trading desk across Q1 2024.
-- PnL formula: SUM(quantity * price * direction_sign) - SUM(commission)
-- where direction_sign = -1 for BUY, +1 for SELL.
--
-- Expected output columns: desk, total_pnl
-- Ordered by: total_pnl DESC
-- Should produce exactly one row per desk.

SELECT
    t.desk,
    ROUND(SUM(tr.quantity * tr.price * CASE tr.direction
        WHEN 'BUY' THEN -1 WHEN 'SELL' THEN 1 END)
        - SUM(COALESCE(tr.commission, 0)), 2) AS total_pnl
FROM traders t
JOIN trades tr ON t.id = tr.trader_id
WHERE tr.trade_date >= '2024-01-01'
  AND tr.trade_date <= '2024-03-31'
GROUP BY t.desk
ORDER BY total_pnl DESC;
