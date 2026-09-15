/* Daily revenue aggregation by product category.
   Tracks total revenue and order counts per day per category. */
MODEL (
  name analytics.daily_revenue,
  kind INCREMENTAL_BY_TIME_RANGE (
    time_column revenue_date
  ),
  grain (revenue_date, category),
  audits (
    assert_positive_revenue
  )
);

SELECT
  o.order_timestamp AS revenue_date,
  o.category,
  SUM(o.amount) AS total_revenue,
  COUNT(*) AS order_count
FROM intermediate.int_order_products o
GROUP BY 1, 2
