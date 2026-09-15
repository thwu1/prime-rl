-- Query 5: Trader Performance Ranking by Region
-- ========================================
-- Rank traders by their Q1 2024 P&L within each region.
-- PnL formula follows the standard: SUM(qty * price * dir_sign) - SUM(commission)
--
-- Expected output columns: name, desk, region, pnl, region_rank
-- Ordered by: region ASC, region_rank ASC
-- Only settled trades in Q1 2024 should be considered.

SELECT
    t.name,
    t.desk,
    t.region,
    ROUND(SUM(tr.quantity * tr.price * CASE tr.direction
        WHEN 'BUY' THEN -1 WHEN 'SELL' THEN 1 END)
        - SUM(tr.commission), 2) AS pnl,
    RANK() OVER (PARTITION BY t.desk ORDER BY
        SUM(tr.quantity * tr.price * CASE tr.direction
            WHEN 'BUY' THEN -1 WHEN 'SELL' THEN 1 END)
        - SUM(tr.commission) DESC
    ) AS region_rank
FROM traders t
JOIN trades tr ON t.id = tr.trader_id
WHERE tr.status = 'settled'
  AND tr.trade_date BETWEEN '2024-01-01' AND '2024-03-31'
GROUP BY t.id, t.name, t.desk, t.region
ORDER BY t.region, region_rank;
