-- Tag-level revenue analysis by unnesting tags
-- Produces: tag_name, txn_count, total_revenue, departments
SELECT
    tag AS tag_name,
    COUNT(*) AS txn_count,
    SUM(t.amount) AS total_revenue,
    sorted_unique_array(ARRAY_AGG(d.dept_name ORDER BY d.dept_name)) AS departments
FROM transactions t
JOIN employees e ON t.emp_id = e.emp_id
JOIN departments d ON e.dept_id = d.dept_id
CROSS JOIN LATERAL UNNEST(t.tags) AS tag
GROUP BY tag
ORDER BY total_revenue DESC;
