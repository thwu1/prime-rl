#!/bin/bash

# Start PostgreSQL
pg_ctlcluster 16 main start 2>/dev/null || true
sleep 2

# Create database and load schema
psql -U postgres -c "CREATE DATABASE analytics_db;" 2>/dev/null || true
psql -U postgres -d analytics_db -f /app/schema.sql

# -- Fix the sorted_unique_array function: add DISTINCT --
psql -U postgres -d analytics_db << 'FUNCFIX'
CREATE OR REPLACE FUNCTION sorted_unique_array(arr TEXT[])
RETURNS TEXT[] AS $$
BEGIN
    RETURN (SELECT ARRAY_AGG(DISTINCT x ORDER BY x) FROM UNNEST(arr) AS x);
END;
$$ LANGUAGE plpgsql IMMUTABLE;
FUNCFIX

# Also update the schema.sql file so it persists across reloads
sed -i 's/ARRAY_AGG(x ORDER BY x)/ARRAY_AGG(DISTINCT x ORDER BY x)/' /app/schema.sql

# -- Fix array_intersect function: UNION -> INTERSECT --
psql -U postgres -d analytics_db << 'FUNCFIX2'
CREATE OR REPLACE FUNCTION array_intersect(a TEXT[], b TEXT[])
RETURNS TEXT[] AS $$
BEGIN
    IF a IS NULL OR b IS NULL THEN
        RETURN NULL;
    END IF;
    RETURN COALESCE(
        (SELECT ARRAY_AGG(x ORDER BY x)
         FROM (SELECT UNNEST(a) AS x INTERSECT SELECT UNNEST(b) AS x) sub),
        '{}'::TEXT[]
    );
END;
$$ LANGUAGE plpgsql IMMUTABLE;
FUNCFIX2

sed -i 's/SELECT UNNEST(a) AS x UNION SELECT UNNEST(b)/SELECT UNNEST(a) AS x INTERSECT SELECT UNNEST(b)/' /app/schema.sql

# -- Fix Q1: Recursive CTE for root dept + GROUPING() bitmask --

cat > /app/queries/q1_hierarchy_cube.sql << 'ENDSQL'
WITH RECURSIVE dept_hierarchy AS (
    SELECT dept_id, dept_name, dept_name AS root_dept
    FROM departments
    WHERE parent_dept_id IS NULL
    UNION ALL
    SELECT d.dept_id, d.dept_name, h.root_dept
    FROM departments d
    JOIN dept_hierarchy h ON d.parent_dept_id = h.dept_id
)
SELECT
    CASE GROUPING(e.region, dh.root_dept)
        WHEN 0 THEN 'detail'
        WHEN 1 THEN 'region_total'
        WHEN 2 THEN 'dept_total'
        WHEN 3 THEN 'grand_total'
    END AS report_level,
    CASE
        WHEN GROUPING(e.region) = 1 THEN 'All Regions'
        WHEN e.region IS NULL THEN 'Unknown'
        ELSE e.region
    END AS region_display,
    CASE
        WHEN GROUPING(dh.root_dept) = 1 THEN 'All Departments'
        ELSE dh.root_dept
    END AS department_display,
    SUM(t.amount) AS total_amount,
    COUNT(*) AS txn_count
FROM transactions t
JOIN employees e ON t.emp_id = e.emp_id
JOIN dept_hierarchy dh ON e.dept_id = dh.dept_id
GROUP BY CUBE(e.region, dh.root_dept)
ORDER BY
    GROUPING(e.region, dh.root_dept),
    e.region NULLS LAST,
    dh.root_dept;
ENDSQL

# -- Fix Q2: Recursive CTE + ROWS frame + tiebreaker + root dept partition --

cat > /app/queries/q2_window_analytics.sql << 'ENDSQL'
WITH RECURSIVE dept_hierarchy AS (
    SELECT dept_id, dept_name, dept_name AS root_dept
    FROM departments
    WHERE parent_dept_id IS NULL
    UNION ALL
    SELECT d.dept_id, d.dept_name, h.root_dept
    FROM departments d
    JOIN dept_hierarchy h ON d.parent_dept_id = h.dept_id
)
SELECT
    e.emp_id AS employee_id,
    dh.root_dept AS top_department,
    t.txn_date,
    t.product,
    t.amount,
    SUM(t.amount) OVER w AS running_total,
    LAG(t.amount) OVER w AS prev_amount,
    ROUND(AVG(t.amount) OVER (
        PARTITION BY e.emp_id
        ORDER BY t.txn_date, t.txn_id
        ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
    ), 2) AS moving_avg_3,
    DENSE_RANK() OVER (
        PARTITION BY dh.root_dept
        ORDER BY t.amount DESC
    ) AS dept_amount_rank
FROM transactions t
JOIN employees e ON t.emp_id = e.emp_id
JOIN dept_hierarchy dh ON e.dept_id = dh.dept_id
WINDOW w AS (
    PARTITION BY e.emp_id
    ORDER BY t.txn_date, t.txn_id
    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
)
ORDER BY e.emp_id, t.txn_date, t.txn_id;
ENDSQL

# -- Fix Q3: LEFT JOIN + empty array handling + root dept + COALESCE + DISTINCT --

cat > /app/queries/q3_tag_revenue.sql << 'ENDSQL'
WITH RECURSIVE dept_hierarchy AS (
    SELECT dept_id, dept_name, dept_name AS root_dept
    FROM departments
    WHERE parent_dept_id IS NULL
    UNION ALL
    SELECT d.dept_id, d.dept_name, h.root_dept
    FROM departments d
    JOIN dept_hierarchy h ON d.parent_dept_id = h.dept_id
)
SELECT
    COALESCE(tag, 'untagged') AS tag_name,
    COUNT(*) AS txn_count,
    SUM(t.amount) AS total_revenue,
    ARRAY_AGG(DISTINCT dh.root_dept ORDER BY dh.root_dept) AS departments
FROM transactions t
JOIN employees e ON t.emp_id = e.emp_id
JOIN dept_hierarchy dh ON e.dept_id = dh.dept_id
LEFT JOIN LATERAL UNNEST(
    CASE WHEN t.tags IS NULL OR t.tags = '{}' THEN ARRAY[NULL::TEXT]
    ELSE t.tags END
) AS tag ON TRUE
GROUP BY COALESCE(tag, 'untagged')
ORDER BY total_revenue DESC;
ENDSQL

# -- Fix Q4: Daily dedup + partition by employee + DENSE_RANK --

cat > /app/queries/q4_streak_analysis.sql << 'ENDSQL'
WITH daily AS (
    SELECT
        emp_id AS employee_id,
        txn_date,
        SUM(amount) AS daily_revenue
    FROM transactions
    GROUP BY emp_id, txn_date
),
numbered AS (
    SELECT
        employee_id,
        txn_date,
        daily_revenue,
        txn_date - (ROW_NUMBER() OVER (
            PARTITION BY employee_id
            ORDER BY txn_date
        ))::int AS island_key
    FROM daily
),
streaks AS (
    SELECT
        employee_id,
        MIN(txn_date) AS streak_start,
        MAX(txn_date) AS streak_end,
        COUNT(*) AS streak_days,
        SUM(daily_revenue) AS streak_revenue
    FROM numbered
    GROUP BY employee_id, island_key
)
SELECT
    employee_id,
    streak_start,
    streak_end,
    streak_days,
    streak_revenue,
    DENSE_RANK() OVER (ORDER BY streak_days DESC, streak_revenue DESC) AS streak_rank
FROM streaks
ORDER BY streak_rank, employee_id;
ENDSQL

# -- Fix Q5: Root dept + department partition + PERCENT_RANK + DESC order --

cat > /app/queries/q5_peer_comparison.sql << 'ENDSQL'
WITH RECURSIVE dept_hierarchy AS (
    SELECT dept_id, dept_name, dept_name AS root_dept
    FROM departments
    WHERE parent_dept_id IS NULL
    UNION ALL
    SELECT d.dept_id, d.dept_name, h.root_dept
    FROM departments d
    JOIN dept_hierarchy h ON d.parent_dept_id = h.dept_id
)
SELECT
    t.txn_id,
    e.emp_id AS employee_id,
    dh.root_dept AS department,
    t.amount,
    ROUND(AVG(t.amount) OVER (PARTITION BY dh.root_dept), 2) AS dept_avg,
    ROUND(AVG(t.amount) OVER (), 2) AS company_avg,
    ROUND((t.amount - AVG(t.amount) OVER (PARTITION BY dh.root_dept)) /
          AVG(t.amount) OVER (PARTITION BY dh.root_dept) * 100, 2) AS dept_deviation_pct,
    ROUND(PERCENT_RANK() OVER (ORDER BY t.amount)::NUMERIC, 4) AS company_rank_pct
FROM transactions t
JOIN employees e ON t.emp_id = e.emp_id
JOIN dept_hierarchy dh ON e.dept_id = dh.dept_id
ORDER BY company_rank_pct DESC, t.txn_id;
ENDSQL

# -- Fix Q6: Separate amount/tag aggregation + root dept + ROWS frame + LAG(1) --

cat > /app/queries/q6_priority_forecast.sql << 'ENDSQL'
WITH RECURSIVE dept_hierarchy AS (
    SELECT dept_id, dept_name, dept_name AS root_dept
    FROM departments
    WHERE parent_dept_id IS NULL
    UNION ALL
    SELECT d.dept_id, d.dept_name, h.root_dept
    FROM departments d
    JOIN dept_hierarchy h ON d.parent_dept_id = h.dept_id
),
daily_amounts AS (
    SELECT
        dh.root_dept AS department,
        t.txn_date,
        SUM(t.amount) AS daily_revenue,
        ROUND(SUM(t.amount * t.priority)::NUMERIC / SUM(t.priority), 2) AS weighted_revenue
    FROM transactions t
    JOIN employees e ON t.emp_id = e.emp_id
    JOIN dept_hierarchy dh ON e.dept_id = dh.dept_id
    GROUP BY dh.root_dept, t.txn_date
),
daily_tags_cte AS (
    SELECT
        dh.root_dept AS department,
        t.txn_date,
        COALESCE(
            sorted_unique_array(
                ARRAY_AGG(unnested_tag) FILTER (WHERE unnested_tag IS NOT NULL)
            ),
            '{}'::TEXT[]
        ) AS daily_tags
    FROM transactions t
    JOIN employees e ON t.emp_id = e.emp_id
    JOIN dept_hierarchy dh ON e.dept_id = dh.dept_id
    LEFT JOIN LATERAL UNNEST(
        CASE WHEN t.tags IS NULL OR t.tags = '{}' THEN ARRAY[NULL::TEXT]
        ELSE t.tags END
    ) AS unnested_tag ON TRUE
    GROUP BY dh.root_dept, t.txn_date
),
daily_data AS (
    SELECT a.department, a.txn_date, a.daily_revenue, a.weighted_revenue, t.daily_tags
    FROM daily_amounts a
    JOIN daily_tags_cte t USING (department, txn_date)
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
            ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
        ), 2) AS rolling_weighted_3d,
        SUM(daily_revenue) OVER (
            PARTITION BY department
            ORDER BY txn_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS cumulative_revenue,
        daily_tags,
        array_intersect(
            daily_tags,
            LAG(daily_tags) OVER (
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
ENDSQL

# Verify all queries run without errors
echo "=== Verifying Q1 ==="
psql -U postgres -d analytics_db -f /app/queries/q1_hierarchy_cube.sql
echo ""
echo "=== Verifying Q2 ==="
psql -U postgres -d analytics_db -f /app/queries/q2_window_analytics.sql
echo ""
echo "=== Verifying Q3 ==="
psql -U postgres -d analytics_db -f /app/queries/q3_tag_revenue.sql
echo ""
echo "=== Verifying Q4 ==="
psql -U postgres -d analytics_db -f /app/queries/q4_streak_analysis.sql
echo ""
echo "=== Verifying Q5 ==="
psql -U postgres -d analytics_db -f /app/queries/q5_peer_comparison.sql
echo ""
echo "=== Verifying Q6 ==="
psql -U postgres -d analytics_db -f /app/queries/q6_priority_forecast.sql
