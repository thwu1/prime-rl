-- Consecutive daily sales streak detection per employee
-- Produces: employee_id, streak_start, streak_end, streak_days, streak_revenue, streak_rank
WITH numbered AS (
    SELECT
        emp_id AS employee_id,
        txn_date,
        amount,
        txn_date - (ROW_NUMBER() OVER (ORDER BY txn_date))::int AS island_key
    FROM transactions
),
streaks AS (
    SELECT
        employee_id,
        MIN(txn_date) AS streak_start,
        MAX(txn_date) AS streak_end,
        COUNT(*) AS streak_days,
        SUM(amount) AS streak_revenue
    FROM numbered
    GROUP BY employee_id, island_key
)
SELECT
    employee_id,
    streak_start,
    streak_end,
    streak_days,
    streak_revenue,
    RANK() OVER (ORDER BY streak_days DESC, streak_revenue DESC) AS streak_rank
FROM streaks
ORDER BY streak_rank, employee_id;
