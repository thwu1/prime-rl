-- Temporal Interval Reconciliation Engine - Correct Solution

DROP VIEW IF EXISTS v_effective_billing CASCADE;
DROP VIEW IF EXISTS v_scheduling_conflicts CASCADE;
DROP VIEW IF EXISTS v_merged_assignments CASCADE;
DROP FUNCTION IF EXISTS fn_team_utilization CASCADE;

------------------------------------------------------------
-- View 1: v_merged_assignments
-- Uses gap-and-island technique with running MAX window function
------------------------------------------------------------
CREATE OR REPLACE VIEW v_merged_assignments AS
WITH ordered AS (
    SELECT
        employee_id,
        project_id,
        start_date,
        end_date,
        MAX(end_date) OVER (
            PARTITION BY employee_id, project_id
            ORDER BY start_date, end_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ) AS prev_max_end
    FROM project_assignments
),
gaps AS (
    SELECT
        employee_id,
        project_id,
        start_date,
        end_date,
        CASE
            WHEN prev_max_end IS NULL THEN 1
            WHEN start_date > prev_max_end + 1 THEN 1
            ELSE 0
        END AS is_new_group
    FROM ordered
),
groups AS (
    SELECT
        employee_id,
        project_id,
        start_date,
        end_date,
        SUM(is_new_group) OVER (
            PARTITION BY employee_id, project_id
            ORDER BY start_date, end_date
        ) AS grp
    FROM gaps
)
SELECT
    employee_id,
    project_id,
    MIN(start_date) AS start_date,
    MAX(end_date) AS end_date
FROM groups
GROUP BY employee_id, project_id, grp;

------------------------------------------------------------
-- View 2: v_scheduling_conflicts
-- Self-join on merged assignments to find cross-project overlaps
------------------------------------------------------------
CREATE OR REPLACE VIEW v_scheduling_conflicts AS
SELECT
    a.employee_id,
    a.project_id AS project_a,
    b.project_id AS project_b,
    GREATEST(a.start_date, b.start_date) AS conflict_start,
    LEAST(a.end_date, b.end_date) AS conflict_end
FROM v_merged_assignments a
JOIN v_merged_assignments b
    ON a.employee_id = b.employee_id
    AND a.project_id < b.project_id
    AND a.start_date <= b.end_date
    AND b.start_date <= a.end_date;

------------------------------------------------------------
-- View 3: v_effective_billing
-- Temporal join: split merged assignments at billing rate boundaries
------------------------------------------------------------
CREATE OR REPLACE VIEW v_effective_billing AS
SELECT
    m.employee_id,
    m.project_id,
    GREATEST(m.start_date, b.effective_from) AS segment_start,
    LEAST(m.end_date, b.effective_to) AS segment_end,
    b.hourly_rate,
    (LEAST(m.end_date, b.effective_to) - GREATEST(m.start_date, b.effective_from) + 1) AS segment_days,
    b.hourly_rate * (LEAST(m.end_date, b.effective_to) - GREATEST(m.start_date, b.effective_from) + 1) AS segment_cost
FROM v_merged_assignments m
JOIN billing_rates b
    ON m.employee_id = b.employee_id
    AND m.start_date <= b.effective_to
    AND m.end_date >= b.effective_from;

------------------------------------------------------------
-- Function: fn_team_utilization
-- Recursive hierarchy traversal + cross-project interval dedup
------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_team_utilization(
    p_manager_id INTEGER,
    p_start DATE,
    p_end DATE
)
RETURNS TABLE (
    employee_id INTEGER,
    employee_name VARCHAR,
    assigned_days INTEGER,
    period_days INTEGER,
    utilization_pct NUMERIC
)
AS $$
BEGIN
    RETURN QUERY
    WITH RECURSIVE team AS (
        -- Direct reports
        SELECT e.employee_id, e.employee_name
        FROM employee_hierarchy e
        WHERE e.manager_id = p_manager_id
        UNION ALL
        -- Indirect reports (recursive)
        SELECT e.employee_id, e.employee_name
        FROM employee_hierarchy e
        JOIN team t ON e.manager_id = t.employee_id
    ),
    -- Clip merged assignments to the query period
    clipped AS (
        SELECT
            m.employee_id AS employee_id,
            GREATEST(m.start_date, p_start) AS start_date,
            LEAST(m.end_date, p_end) AS end_date
        FROM v_merged_assignments m
        JOIN team t ON m.employee_id = t.employee_id
        WHERE m.start_date <= p_end
          AND m.end_date >= p_start
    ),
    -- Re-merge across projects using the same gap-and-island technique
    cross_ordered AS (
        SELECT
            c.employee_id AS eid,
            c.start_date AS sd,
            c.end_date AS ed,
            MAX(c.end_date) OVER (
                PARTITION BY c.employee_id
                ORDER BY c.start_date, c.end_date
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
            ) AS prev_max_end
        FROM clipped c
    ),
    cross_gaps AS (
        SELECT
            co.eid,
            co.sd,
            co.ed,
            CASE
                WHEN co.prev_max_end IS NULL THEN 1
                WHEN co.sd > co.prev_max_end + 1 THEN 1
                ELSE 0
            END AS is_new_group
        FROM cross_ordered co
    ),
    cross_groups AS (
        SELECT
            cg.eid,
            cg.sd,
            cg.ed,
            SUM(cg.is_new_group) OVER (
                PARTITION BY cg.eid
                ORDER BY cg.sd, cg.ed
            ) AS grp
        FROM cross_gaps cg
    ),
    merged_all AS (
        SELECT
            cg2.eid,
            MIN(cg2.sd) AS sd,
            MAX(cg2.ed) AS ed
        FROM cross_groups cg2
        GROUP BY cg2.eid, cg2.grp
    ),
    util AS (
        SELECT
            ma.eid,
            SUM(ma.ed - ma.sd + 1)::INTEGER AS total_days
        FROM merged_all ma
        GROUP BY ma.eid
    )
    SELECT
        t.employee_id,
        t.employee_name,
        COALESCE(u.total_days, 0)::INTEGER AS assigned_days,
        (p_end - p_start + 1)::INTEGER AS period_days,
        ROUND(100.0 * COALESCE(u.total_days, 0) / (p_end - p_start + 1), 2) AS utilization_pct
    FROM team t
    LEFT JOIN util u ON t.employee_id = u.eid
    ORDER BY t.employee_id;
END;
$$ LANGUAGE plpgsql;
