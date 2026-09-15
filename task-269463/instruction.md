A production Oracle 19c OLTP database (ECOMDB) serving an e-commerce platform is experiencing severe performance degradation during peak holiday traffic. The DBA team captured diagnostic data through multiple mechanisms and stored it across several formats:

- `/app/ecomdb_diag.db` — SQLite database containing snapshots of V$ dynamic performance views (sysstat, system\_event, librarycache, sql\_area, sql\_plan\_operations, sgastat), instance parameters, and operational constraints
- `/app/logs/alert_ecomdb.log` — Raw Oracle alert log text from the degraded period (traditional format, not XML)
- `/app/exports/db_cache_advice.csv` — CSV export of V$DB\_CACHE\_ADVICE across both snapshots and multiple buffer pools
- `/app/exports/pga_target_advice.csv` — CSV export of V$PGA\_TARGET\_ADVICE across both snapshots

The `snapshots` table in the SQLite database describes the two capture periods. Operational constraints — including the maximum SGA memory budget — are in the `constraints` table.

Perform a comprehensive performance triage: correlate data across all sources to determine what changed, identify root causes of degradation ranked by impact, and design an optimal remediation configuration satisfying all operational constraints.

Write your results to `/app/analysis/`:

**`root_cause_analysis.json`** — A JSON array of identified root causes, ordered from highest to lowest severity. Each element: `{"cause": "<description>", "severity": "critical|high|medium|low", "evidence": "<supporting metric or observation>", "category": "<parsing|memory|sql|contention|io>"}`. Must pass `jq` type validation.

**`optimal_config.json`** — A JSON object with:
- `parameters`: object mapping Oracle parameter names to recommended values (integers for memory parameters in bytes, strings for non-numeric parameters)
- `estimated_cache_improvement_factor`: estimated physical read factor at the recommended buffer cache size (from advisory analysis)
- `memory_budget_used_bytes`: total SGA memory in the recommended configuration (must satisfy the budget constraint)
- `problematic_sql_ids`: array of SQL\_ID strings requiring tuning
- `ora_04031_count`: number of ORA-04031 errors counted from the alert log

**`cache_advisory.svg`** — An SVG chart generated with `gnuplot` showing the buffer cache advisory curve (cache size in MB vs. estimated physical read factor) for the degraded snapshot's DEFAULT pool. Annotate the current operating point and the recommended size.

**`tuning_actions.sql`** — ALTER SYSTEM SET commands (with SCOPE=SPFILE) and any supporting DDL implementing the remediation.