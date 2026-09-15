-- Annual Revenue Trend
-- Quarterly revenue and distinct order counts across all years
SELECT
    dd.year,
    dd.quarter,
    SUM(f.extended_price * (1 - f.discount)) AS quarterly_revenue,
    COUNT(DISTINCT f.order_key) AS num_orders
FROM fact_sales f
JOIN dim_date dd ON f.order_date_key = dd.date_key
GROUP BY dd.year, dd.quarter
ORDER BY dd.year, dd.quarter;
