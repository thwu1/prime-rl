-- Q1: Customer spend analysis for a specific month
SELECT c.name, c.region,
       COUNT(o.id) AS order_count,
       SUM(o.total_amount) AS total_spent
FROM customers c
JOIN orders o ON o.customer_id = c.id
WHERE o.order_date >= '2023-06-01'
  AND o.order_date < '2023-07-01'
GROUP BY c.id, c.name, c.region
HAVING SUM(o.total_amount) > 500
ORDER BY total_spent DESC
LIMIT 20;
