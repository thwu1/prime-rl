The PostgreSQL database defined in `/app/setup.sql` has three tables: `employee_hierarchy` (org tree: `employee_id`, `manager_id`, `employee_name`, `department`), `project_assignments` (`assignment_id`, `employee_id`, `project_id`, `start_date`, `end_date` — contains overlapping and adjacent intervals), and `billing_rates` (SCD Type 2: `employee_id`, `hourly_rate`, `effective_from`, `effective_to` where `'9999-12-31'` marks current).

Modify `/app/solution.sql` to correctly implement these four database objects:

**View `v_merged_assignments`**
Columns: `employee_id`, `project_id`, `start_date`, `end_date`
Merge overlapping or adjacent (`end_date + 1 day = next start_date`) assignment intervals for each `(employee_id, project_id)` pair. Non-overlapping intervals with gaps remain as separate rows.

**View `v_scheduling_conflicts`**
Columns: `employee_id`, `project_a`, `project_b`, `conflict_start`, `conflict_end`
Using merged assignments, find time intervals where an employee is assigned to two different projects simultaneously. Ensure `project_a < project_b`. Each conflict pair produces one row showing the intersection interval.

**View `v_effective_billing`**
Columns: `employee_id`, `project_id`, `segment_start`, `segment_end`, `hourly_rate`, `segment_days`, `segment_cost`
Split each merged assignment into sub-segments at billing rate boundaries. `segment_days` equals `segment_end - segment_start + 1` (inclusive calendar days). `segment_cost` equals `hourly_rate * segment_days`.

**Function `fn_team_utilization(p_manager_id INTEGER, p_start DATE, p_end DATE)`**
Returns: `employee_id INTEGER`, `employee_name VARCHAR`, `assigned_days INTEGER`, `period_days INTEGER`, `utilization_pct NUMERIC`
Finds all direct and indirect reports under `p_manager_id` (excluding the manager). For each report, calculates days with any project assignment within `[p_start, p_end]`, using merged assignments clipped to the period. When assignments on different projects overlap in time, count each calendar day only once. `period_days` equals `p_end - p_start + 1`. `utilization_pct` equals `ROUND(100.0 * assigned_days / period_days, 2)`. Order results by `employee_id`.

Start PostgreSQL (connect as the `postgres` superuser), create a database, then execute `/app/setup.sql` followed by `/app/solution.sql`. Verification queries the views and function directly.
