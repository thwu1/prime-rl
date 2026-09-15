-- Fixed Fulfillment Analytics Pipeline
--

-----------------------------------------------------------------------
-- View 1: Revenue aggregated by hub warehouse and customer tier
-----------------------------------------------------------------------
CREATE OR REPLACE VIEW v_hierarchy_revenue AS
WITH RECURSIVE warehouse_tree AS (
    SELECT warehouse_id, warehouse_name, parent_id,
           warehouse_name AS hub_name
    FROM warehouses
    WHERE parent_id IS NULL

    UNION ALL

    SELECT w.warehouse_id, w.warehouse_name, w.parent_id,
           wt.hub_name AS hub_name
    FROM warehouses w
    JOIN warehouse_tree wt ON w.parent_id = wt.warehouse_id
)
SELECT
    wt.hub_name,
    o.metadata ->> 'customer_tier' AS customer_tier,
    SUM(o.total_amount) AS total_revenue
FROM warehouse_tree wt
JOIN orders o ON o.warehouse_id = wt.warehouse_id
GROUP BY wt.hub_name, o.metadata ->> 'customer_tier';


-----------------------------------------------------------------------
-- View 2: 7-day rolling average of daily delivery completion rates
-----------------------------------------------------------------------
CREATE OR REPLACE VIEW v_rolling_fulfillment AS
WITH daily_rates AS (
    SELECT
        w.region,
        DATE(oe.completed_at) AS completion_date,
        COUNT(CASE WHEN oe.status = 'completed' THEN 1 END)::NUMERIC /
            NULLIF(COUNT(*)::NUMERIC, 0) AS daily_rate
    FROM order_events oe
    JOIN orders o ON o.order_id = oe.order_id
    JOIN warehouses w ON w.warehouse_id = o.warehouse_id
    WHERE oe.stage_id = 5
    GROUP BY w.region, DATE(oe.completed_at)
)
SELECT
    region,
    completion_date AS calc_date,
    AVG(daily_rate) OVER (
        PARTITION BY region
        ORDER BY completion_date
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) AS rolling_rate
FROM daily_rates;


-----------------------------------------------------------------------
-- View 3: Orders that skipped expected fulfillment stages
-----------------------------------------------------------------------
CREATE OR REPLACE VIEW v_stage_gaps AS
WITH order_stage_list AS (
    SELECT
        oe.order_id,
        fs.stage_order
    FROM order_events oe
    JOIN fulfillment_stages fs ON fs.stage_id = oe.stage_id
),
order_ranges AS (
    SELECT
        order_id,
        MAX(stage_order) AS max_stage
    FROM order_stage_list
    GROUP BY order_id
),
expected_stages AS (
    SELECT
        r.order_id,
        generate_series(1, r.max_stage) AS expected_stage
    FROM order_ranges r
),
missing_stages AS (
    SELECT
        es.order_id,
        es.expected_stage
    FROM expected_stages es
    LEFT JOIN order_stage_list osl
        ON osl.order_id = es.order_id
        AND osl.stage_order = es.expected_stage
    WHERE osl.order_id IS NULL
)
SELECT
    ms.order_id,
    w.warehouse_type,
    ARRAY_AGG(ms.expected_stage ORDER BY ms.expected_stage) AS missed_stages
FROM missing_stages ms
JOIN orders o ON o.order_id = ms.order_id
JOIN warehouses w ON w.warehouse_id = o.warehouse_id
GROUP BY ms.order_id, w.warehouse_type;


-----------------------------------------------------------------------
-- View 4: Quarter-over-quarter revenue growth rate per region
-----------------------------------------------------------------------
CREATE OR REPLACE VIEW v_quarterly_growth AS
WITH quarterly_revenue AS (
    SELECT
        w.region,
        EXTRACT(YEAR FROM o.order_date)::INTEGER AS year,
        EXTRACT(QUARTER FROM o.order_date)::INTEGER AS quarter,
        SUM(o.total_amount) AS total_revenue
    FROM orders o
    JOIN warehouses w ON w.warehouse_id = o.warehouse_id
    GROUP BY w.region,
             EXTRACT(YEAR FROM o.order_date),
             EXTRACT(QUARTER FROM o.order_date)
)
SELECT
    region,
    year,
    quarter,
    (total_revenue - LAG(total_revenue) OVER w) /
        NULLIF(LAG(total_revenue) OVER w, 0) AS growth_rate
FROM quarterly_revenue
WINDOW w AS (PARTITION BY region ORDER BY year, quarter);


-----------------------------------------------------------------------
-- View 5: Per-warehouse fulfillment speed metrics
-----------------------------------------------------------------------
CREATE OR REPLACE VIEW v_fulfillment_velocity AS
WITH complete_orders AS (
    SELECT oe.order_id
    FROM order_events oe
    WHERE oe.status = 'completed'
    GROUP BY oe.order_id
    HAVING COUNT(DISTINCT oe.stage_id) = 5
),
fulfillment_times AS (
    SELECT
        o.warehouse_id,
        w.warehouse_name,
        EXTRACT(EPOCH FROM (oe.completed_at - o.order_date)) / 3600.0 AS hours
    FROM complete_orders co
    JOIN orders o ON o.order_id = co.order_id
    JOIN order_events oe ON oe.order_id = co.order_id
        AND oe.stage_id = 5 AND oe.status = 'completed'
    JOIN warehouses w ON w.warehouse_id = o.warehouse_id
)
SELECT
    warehouse_id,
    warehouse_name,
    COUNT(*)::INTEGER AS order_count,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY hours)::NUMERIC AS median_hours,
    PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY hours)::NUMERIC AS p90_hours,
    (PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY hours) /
     NULLIF(PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY hours), 0))::NUMERIC AS velocity_score
FROM fulfillment_times
GROUP BY warehouse_id, warehouse_name;


-----------------------------------------------------------------------
-- View 6: Composite per-region health score
-----------------------------------------------------------------------
CREATE OR REPLACE VIEW v_health_score AS
WITH RECURSIVE hierarchy AS (
    SELECT warehouse_id, region, 1 AS depth
    FROM warehouses WHERE parent_id IS NULL
    UNION ALL
    SELECT w.warehouse_id, w.region, h.depth + 1
    FROM warehouses w JOIN hierarchy h ON w.parent_id = h.warehouse_id
),
depth_by_region AS (
    SELECT region, MAX(depth) AS max_depth
    FROM hierarchy GROUP BY region
),
revenue_by_region AS (
    SELECT w.region, SUM(o.total_amount) AS total_revenue
    FROM orders o JOIN warehouses w ON w.warehouse_id = o.warehouse_id
    GROUP BY w.region
),
max_revenue AS (
    SELECT MAX(total_revenue) AS max_rev FROM revenue_by_region
),
osl AS (
    SELECT oe.order_id, fs.stage_order
    FROM order_events oe
    JOIN fulfillment_stages fs ON fs.stage_id = oe.stage_id
),
omax AS (
    SELECT order_id, MAX(stage_order) AS max_stage
    FROM osl GROUP BY order_id
),
expected AS (
    SELECT om.order_id, generate_series(1, om.max_stage) AS expected_stage
    FROM omax om
),
orders_with_gaps AS (
    SELECT DISTINCT e.order_id
    FROM expected e
    LEFT JOIN osl ON osl.order_id = e.order_id
        AND osl.stage_order = e.expected_stage
    WHERE osl.order_id IS NULL
),
gap_counts AS (
    SELECT w.region,
           COUNT(DISTINCT owg.order_id) AS gap_orders,
           COUNT(DISTINCT o.order_id) AS total_orders
    FROM orders o
    JOIN warehouses w ON w.warehouse_id = o.warehouse_id
    LEFT JOIN orders_with_gaps owg ON owg.order_id = o.order_id
    GROUP BY w.region
),
quarterly_rev AS (
    SELECT w.region,
           EXTRACT(YEAR FROM o.order_date)::INTEGER AS year,
           EXTRACT(QUARTER FROM o.order_date)::INTEGER AS quarter,
           SUM(o.total_amount) AS total_revenue
    FROM orders o JOIN warehouses w ON w.warehouse_id = o.warehouse_id
    GROUP BY w.region,
             EXTRACT(YEAR FROM o.order_date),
             EXTRACT(QUARTER FROM o.order_date)
),
growth AS (
    SELECT region, year, quarter,
           (total_revenue - LAG(total_revenue) OVER (
               PARTITION BY region ORDER BY year, quarter
           )) / NULLIF(LAG(total_revenue) OVER (
               PARTITION BY region ORDER BY year, quarter
           ), 0) AS growth_rate
    FROM quarterly_rev
),
latest_growth AS (
    SELECT DISTINCT ON (region) region, growth_rate
    FROM growth WHERE growth_rate IS NOT NULL
    ORDER BY region, year DESC, quarter DESC
),
complete_orders AS (
    SELECT oe.order_id
    FROM order_events oe
    WHERE oe.status = 'completed'
    GROUP BY oe.order_id
    HAVING COUNT(DISTINCT oe.stage_id) = 5
),
fulfillment_times AS (
    SELECT
        o.warehouse_id,
        EXTRACT(EPOCH FROM (oe.completed_at - o.order_date)) / 3600.0 AS hours
    FROM complete_orders co
    JOIN orders o ON o.order_id = co.order_id
    JOIN order_events oe ON oe.order_id = co.order_id
        AND oe.stage_id = 5 AND oe.status = 'completed'
),
warehouse_velocity AS (
    SELECT
        warehouse_id,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY hours) /
        NULLIF(PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY hours), 0) AS velocity_score
    FROM fulfillment_times
    GROUP BY warehouse_id
),
region_velocity AS (
    SELECT w.region, AVG(wv.velocity_score) AS avg_velocity
    FROM warehouse_velocity wv
    JOIN warehouses w ON w.warehouse_id = wv.warehouse_id
    GROUP BY w.region
)
SELECT
    d.region,
    (1.0 / d.max_depth)::NUMERIC AS depth_score,
    (r.total_revenue / mr.max_rev)::NUMERIC AS revenue_score,
    (1.0 - gc.gap_orders::NUMERIC / gc.total_orders)::NUMERIC AS gap_score,
    COALESCE(lg.growth_rate, 0)::NUMERIC AS trend_score,
    COALESCE(rv.avg_velocity, 0)::NUMERIC AS velocity_score,
    (
        (1.0 / d.max_depth) * 0.25 +
        (r.total_revenue / mr.max_rev) * 0.25 +
        (1.0 - gc.gap_orders::NUMERIC / gc.total_orders) * 0.15 +
        COALESCE(lg.growth_rate, 0) * 0.15 +
        COALESCE(rv.avg_velocity, 0) * 0.20
    )::NUMERIC AS health_score
FROM depth_by_region d
JOIN revenue_by_region r ON r.region = d.region
CROSS JOIN max_revenue mr
JOIN gap_counts gc ON gc.region = d.region
LEFT JOIN latest_growth lg ON lg.region = d.region
LEFT JOIN region_velocity rv ON rv.region = d.region;
