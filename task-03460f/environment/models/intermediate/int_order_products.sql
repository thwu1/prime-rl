/* Intermediate model joining orders with product details.
   Enriches each order with its product metadata. */
MODEL (
  name intermediate.int_order_products,
  kind INCREMENTAL_BY_TIME_RANGE (
    time_column order_timestamp
  ),
  grain order_id
);

SELECT
  o.order_id,
  o.customer_id,
  o.order_timestamp,
  o.amount,
  o.status,
  p.product_name,
  p.category,
  p.unit_price
FROM staging.stg_orders o
INNER JOIN raw.seed_products p
  ON o.product_id = p.product_id
WHERE
  o.order_timestamp BETWEEN @start_ds AND @end_ds
