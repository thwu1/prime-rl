-- Profit by Supplier Nation
-- Net profit per supplier nation per year for parts containing 'green'
-- Uses retail_price as cost proxy since supply cost is not in the model
SELECT
    ds.nation_name AS nation,
    dd.year AS o_year,
    SUM(f.extended_price * (1 - f.discount) - dp.retail_price * f.quantity) AS total_profit
FROM fact_sales f
JOIN dim_supplier ds ON f.supplier_key = ds.supplier_key
JOIN dim_part dp ON f.part_key = dp.part_key
JOIN dim_date dd ON f.order_date_key = dd.date_key
WHERE dp.name LIKE '%green%'
GROUP BY ds.nation_name, dd.year
ORDER BY ds.nation_name, o_year DESC;
