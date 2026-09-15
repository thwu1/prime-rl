-- Per-employee transaction analytics with window functions
-- Produces: employee_id, top_department, txn_date, product, amount,
--           running_total, prev_amount, moving_avg_3, dept_amount_rank
SELECT
    e.emp_id AS employee_id,
    d.dept_name AS top_department,
    t.txn_date,
    t.product,
    t.amount,
    SUM(t.amount) OVER emp_w AS running_total,
    LAG(t.amount) OVER emp_w AS prev_amount,
    ROUND(AVG(t.amount) OVER emp_w, 2) AS moving_avg_3,
    DENSE_RANK() OVER (
        PARTITION BY e.emp_id
        ORDER BY t.amount DESC
    ) AS dept_amount_rank
FROM transactions t
JOIN employees e ON t.emp_id = e.emp_id
JOIN departments d ON e.dept_id = d.dept_id
WINDOW emp_w AS (
    PARTITION BY e.emp_id
    ORDER BY t.txn_date
)
ORDER BY e.emp_id, t.txn_date, t.txn_id;
