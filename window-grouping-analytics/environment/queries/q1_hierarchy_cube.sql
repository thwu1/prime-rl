-- Hierarchical department rollup with CUBE
-- Produces: report_level, region_display, department_display, total_amount, txn_count
SELECT
    CASE
        WHEN d.dept_name IS NULL AND e.region IS NULL THEN 'grand_total'
        WHEN d.dept_name IS NULL THEN 'dept_total'
        WHEN e.region IS NULL THEN 'region_total'
        ELSE 'detail'
    END AS report_level,
    COALESCE(e.region, 'All Regions') AS region_display,
    COALESCE(d.dept_name, 'All Departments') AS department_display,
    SUM(t.amount) AS total_amount,
    COUNT(*) AS txn_count
FROM transactions t
JOIN employees e ON t.emp_id = e.emp_id
JOIN departments d ON e.dept_id = d.dept_id
GROUP BY CUBE(e.region, d.dept_name)
ORDER BY
    CASE
        WHEN e.region IS NULL AND d.dept_name IS NULL THEN 4
        WHEN d.dept_name IS NULL THEN 2
        WHEN e.region IS NULL THEN 3
        ELSE 1
    END,
    e.region NULLS LAST,
    d.dept_name;
