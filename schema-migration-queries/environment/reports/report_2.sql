-- Order Revenue by Customer Region
-- Total order value and order count by customer geographic region
-- for orders placed in calendar year 1995
SELECT
    dc.region_name,
    SUM(f.order_total_price) AS total_revenue,
    COUNT(DISTINCT f.order_key) AS num_orders
FROM fact_sales f
JOIN dim_customer dc ON f.customer_key = dc.customer_key
JOIN dim_date dd ON f.order_date_key = dd.date_key
WHERE dd.year = 1995
GROUP BY dc.region_name
ORDER BY total_revenue DESC;
