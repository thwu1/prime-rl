-- Hierarchical sales report using CUBE
-- Produces: report_level, region_display, department_display, total_amount, txn_count
SELECT
    CASE
        WHEN region IS NULL AND department IS NULL THEN 'grand_total'
        WHEN department IS NULL THEN 'region_total'
        WHEN region IS NULL THEN 'dept_total'
        ELSE 'detail'
    END AS report_level,
    COALESCE(region, 'Unknown') AS region_display,
    COALESCE(department, 'All Departments') AS department_display,
    SUM(amount) AS total_amount,
    COUNT(*) AS txn_count
FROM transactions
GROUP BY CUBE(region, department)
ORDER BY
    GROUPING(region, department),
    region NULLS LAST,
    department;
