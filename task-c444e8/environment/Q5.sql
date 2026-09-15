-- Q5: Order details for a specific customer
SELECT o.id, o.order_date, o.total_amount,
       COUNT(oi.id) AS item_count,
       SUM(oi.quantity) AS total_items
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
WHERE o.customer_id = 42
GROUP BY o.id, o.order_date, o.total_amount
ORDER BY o.order_date DESC;
