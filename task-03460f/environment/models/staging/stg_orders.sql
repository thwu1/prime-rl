/* Staging model for orders - cleans and types raw order data.
   Incremental by time range on the order date. */
MODEL (
  name staging.stg_orders,
  kind INCREMENTAL_BY_TIME_RANGE (
    time_column ordered_at
  ),
  grain order_id
);

SELECT
  order_id,
  customer_id,
  product_id,
  amount,
  CAST(order_date AS DATE) AS order_timestamp,
  status
FROM raw.seed_orders
WHERE
  CAST(order_date AS DATE) BETWEEN @start_ds AND @end_ds
