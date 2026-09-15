-- Q2: Order status distribution with aggregates
SELECT status,
       COUNT(*) AS cnt,
       AVG(total_amount) AS avg_amount,
       SUM(total_amount) AS total
FROM orders
GROUP BY status
ORDER BY total DESC;
