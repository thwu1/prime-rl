-- Quarterly sales report: Q2 2024 revenue by employee
SELECT employee_id, subsidiary_id, SUM(eur_value) as total, COUNT(*) as num_sales
FROM sales
WHERE EXTRACT(YEAR FROM sale_date) = 2024
  AND EXTRACT(QUARTER FROM sale_date) = 2
GROUP BY employee_id, subsidiary_id
ORDER BY total DESC;
