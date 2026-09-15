/* Product performance rankings.
   Aggregates total sales, order frequency, and average order value per product. */
MODEL (
  name analytics.top_products,
  kind FULL
);

SELECT
  category,
  product_name,
  SUM(amount) AS total_sales,
  COUNT(*) AS times_ordered,
  AVG(amount) AS avg_order_amount
FROM intermediate.order_products
GROUP BY 1, 2
ORDER BY total_sales DESC
