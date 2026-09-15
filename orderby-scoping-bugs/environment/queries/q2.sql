-- Report: transaction count by size category, sorted by category
SELECT
    CASE WHEN amount >= 250 THEN 'large' ELSE 'small' END AS amount,
    COUNT(*) AS tx_count
FROM transactions
GROUP BY amount
ORDER BY amount;
