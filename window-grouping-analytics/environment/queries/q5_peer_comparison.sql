-- Per-transaction peer comparison analysis
-- Produces: txn_id, employee_id, department, amount, dept_avg, company_avg,
--           dept_deviation_pct, company_rank_pct
SELECT
    t.txn_id,
    e.emp_id AS employee_id,
    d.dept_name AS department,
    t.amount,
    ROUND(AVG(t.amount) OVER (PARTITION BY e.emp_id), 2) AS dept_avg,
    ROUND(AVG(t.amount) OVER (), 2) AS company_avg,
    ROUND((t.amount - AVG(t.amount) OVER (PARTITION BY e.emp_id)) /
          AVG(t.amount) OVER (PARTITION BY e.emp_id) * 100, 2) AS dept_deviation_pct,
    ROUND(CAST(RANK() OVER (ORDER BY t.amount) AS NUMERIC) /
          CAST(COUNT(*) OVER () AS NUMERIC), 4) AS company_rank_pct
FROM transactions t
JOIN employees e ON t.emp_id = e.emp_id
JOIN departments d ON e.dept_id = d.dept_id
ORDER BY company_rank_pct, t.txn_id;
