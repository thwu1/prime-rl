-- Local Supplier Revenue in ASIA
-- Revenue from transactions where customer and supplier share
-- the same nation within the ASIA region, for orders in 1994
SELECT
    ds.nation_name,
    SUM(f.extended_price * (1 - f.discount)) AS revenue
FROM fact_sales f
JOIN dim_customer dc ON f.customer_key = dc.customer_key
JOIN dim_supplier ds ON f.supplier_key = ds.supplier_key
JOIN dim_date dd ON f.order_date_key = dd.date_key
WHERE dc.nation_name = ds.nation_name
  AND ds.region_name = 'ASIA'
  AND dd.year = 1994
GROUP BY ds.nation_name
ORDER BY revenue DESC;
