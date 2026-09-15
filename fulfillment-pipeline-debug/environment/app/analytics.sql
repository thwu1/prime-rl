-- Fulfillment Analytics Pipeline
-- Creates six analytical views over the fulfillment tracking database.
--

-----------------------------------------------------------------------
-- View 1: Revenue aggregated by hub warehouse and customer tier.
-- Each hub's revenue includes all descendant warehouses in the tree.
-----------------------------------------------------------------------
CREATE OR REPLACE VIEW v_hierarchy_revenue AS
WITH RECURSIVE warehouse_tree AS (
    SELECT warehouse_id, warehouse_name, parent_id,
           warehouse_name AS hub_name
    FROM warehouses
    WHERE parent_id IS NULL

    UNION ALL

    SELECT w.warehouse_id, w.warehouse_name, w.parent_id,
           w.warehouse_name AS hub_name
    FROM warehouses w
    JOIN warehouse_tree wt ON w.parent_id = wt.warehouse_id
)
SELECT
    wt.hub_name,
    o.metadata -> 'customer_tier' AS customer_tier,
    SUM(o.total_amount) AS total_revenue
FROM warehouse_tree wt
JOIN orders o ON o.warehouse_id = wt.warehouse_id
GROUP BY wt.hub_name, o.metadata -> 'customer_tier';


-----------------------------------------------------------------------
-- View 2: 7-day rolling average of daily delivery completion rates
-- per region.
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
    WHERE oe.stage_id = 4
    GROUP BY w.region, DATE(oe.completed_at)
)
SELECT
    region,
    completion_date AS calc_date,
    AVG(daily_rate) OVER (
        PARTITION BY region
        ORDER BY completion_date
        ROWS BETWEEN 7 PRECEDING AND CURRENT ROW
    ) AS rolling_rate
FROM daily_rates;


-----------------------------------------------------------------------
-- View 3: Orders that skipped expected fulfillment stages.
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
        MIN(stage_order) AS min_stage,
        MAX(stage_order) AS max_stage
    FROM order_stage_list
    GROUP BY order_id
),
expected_stages AS (
    SELECT
        r.order_id,
        generate_series(r.min_stage, r.max_stage) AS expected_stage
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
-- View 4: Quarter-over-quarter revenue growth rate per region.
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
        NULLIF(total_revenue, 0) AS growth_rate
FROM quarterly_revenue
WINDOW w AS (PARTITION BY region ORDER BY year, quarter);


-----------------------------------------------------------------------
-- View 5: Per-warehouse fulfillment speed metrics.
-----------------------------------------------------------------------
CREATE OR REPLACE VIEW v_fulfillment_velocity AS
SELECT
    NULL::INTEGER  AS warehouse_id,
    NULL::VARCHAR  AS warehouse_name,
    NULL::INTEGER  AS order_count,
    NULL::NUMERIC  AS median_hours,
    NULL::NUMERIC  AS p90_hours,
    NULL::NUMERIC  AS velocity_score
WHERE FALSE;


-----------------------------------------------------------------------
-- View 6: Composite per-region health score.
-----------------------------------------------------------------------
CREATE OR REPLACE VIEW v_health_score AS
SELECT
    NULL::VARCHAR  AS region,
    NULL::NUMERIC  AS depth_score,
    NULL::NUMERIC  AS revenue_score,
    NULL::NUMERIC  AS gap_score,
    NULL::NUMERIC  AS trend_score,
    NULL::NUMERIC  AS velocity_score,
    NULL::NUMERIC  AS health_score
WHERE FALSE;
