-- Tag frequency and revenue analysis via UNNEST
-- Produces: tag_name, txn_count, total_revenue, departments
SELECT
    tag AS tag_name,
    COUNT(*) AS txn_count,
    SUM(t.amount) AS total_revenue,
    ARRAY_AGG(t.department ORDER BY t.department) AS departments
FROM transactions t
CROSS JOIN LATERAL UNNEST(t.tags) AS tag
GROUP BY tag
ORDER BY total_revenue DESC;
