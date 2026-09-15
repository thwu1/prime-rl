-- Revenue aggregation: total sales for selected subsidiaries
SELECT subsidiary_id,
       SUM(eur_value) as total_revenue,
       COUNT(*) as sale_count
FROM sales
WHERE subsidiary_id IN (1, 2, 3, 4, 5)
GROUP BY subsidiary_id
ORDER BY total_revenue DESC;
