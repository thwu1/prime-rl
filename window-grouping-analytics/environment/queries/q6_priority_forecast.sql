-- Priority-weighted department trend analysis by date
-- Produces: department, txn_date, daily_revenue, weighted_revenue,
--           rolling_weighted_3d, cumulative_revenue, daily_tags,
--           tag_carryover, trend_rank
WITH daily_data AS (
    SELECT
        d.dept_name AS department,
        t.txn_date,
        SUM(t.amount) AS daily_revenue,
        ROUND(SUM(t.amount * t.priority)::NUMERIC / SUM(t.priority), 2) AS weighted_revenue,
        sorted_unique_array(ARRAY_AGG(tag ORDER BY tag)) AS daily_tags
    FROM transactions t
    JOIN employees e ON t.emp_id = e.emp_id
    JOIN departments d ON e.dept_id = d.dept_id
    CROSS JOIN LATERAL UNNEST(t.tags) AS tag
    GROUP BY d.dept_name, t.txn_date
),
with_windows AS (
    SELECT
        department,
        txn_date,
        daily_revenue,
        weighted_revenue,
        ROUND(AVG(weighted_revenue) OVER (
            PARTITION BY department
            ORDER BY txn_date
        ), 2) AS rolling_weighted_3d,
        SUM(daily_revenue) OVER (
            PARTITION BY department
            ORDER BY txn_date
        ) AS cumulative_revenue,
        daily_tags,
        array_intersect(
            daily_tags,
            LAG(daily_tags, 2) OVER (
                PARTITION BY department
                ORDER BY txn_date
            )
        ) AS tag_carryover
    FROM daily_data
)
SELECT
    department,
    txn_date,
    daily_revenue,
    weighted_revenue,
    rolling_weighted_3d,
    cumulative_revenue,
    daily_tags,
    tag_carryover,
    DENSE_RANK() OVER (
        PARTITION BY department
        ORDER BY rolling_weighted_3d DESC
    ) AS trend_rank
FROM with_windows
ORDER BY department, txn_date;
