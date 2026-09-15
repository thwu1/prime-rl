-- Q3: Revenue by product category
SELECT p.category,
       COUNT(DISTINCT oi.order_id) AS num_orders,
       SUM(oi.quantity) AS total_qty,
       SUM(oi.quantity * oi.unit_price) AS revenue
FROM order_items oi
JOIN products p ON oi.product_id = p.id
GROUP BY p.category
ORDER BY revenue DESC;
