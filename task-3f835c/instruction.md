An Oracle 19c e-commerce OLTP database (ECOM_PROD) experienced severe performance degradation during peak hours. Three external consultants independently analyzed the raw incident data and each submitted a diagnostic report. Your task is to determine which consultant produced the most accurate analysis, identify the specific errors in each report, and produce the definitive corrected diagnosis with a working remediation script.

## Input data

- `/app/incident/*.lst` — Raw V$ view exports captured during the incident window, in Oracle SQL\*Plus spool output format. Includes system statistics, wait events, buffer cache advisory, library cache stats, PGA stats, PGA advisory, SQL area metrics, initialization parameters, SGA stats, buffer wait stats, execution plans, and schema definitions. See `/app/incident/README.txt` for a file manifest.
- `/app/baselines/baselines.db` — SQLite database containing the same performance metrics from a healthy baseline period one week before the incident. Tables: `sysstat`, `system_event`, `pgastat`. Use this to assess the severity of observed degradation.
- `/app/reports/consultant_A.json`, `consultant_B.json`, `consultant_C.json` — Three diagnostic reports to evaluate. Each follows the `corrected_diagnosis.json` schema shown below. Each contains one or more errors in computed metrics, diagnoses, or recommendations.

## Required outputs

### `/app/analysis.db`

SQLite database with incident spool data imported into queryable tables. Must contain tables named: `sysstat`, `system_event`, `db_cache_advice`, `librarycache`, `pgastat`, `pga_target_advice`, `sqlarea`.

### `/app/evaluation.json`

Per-consultant evaluation with accuracy scores, rankings, and identified errors:

```json
{
  "consultant_A": {
    "accuracy_score": "<float 0.0-1.0>",
    "rank": "<int 1-3, 1=best>",
    "errors": [
      {"field": "<section.field_name>", "reported": "<value>", "correct": "<value>"}
    ]
  },
  "consultant_B": { "accuracy_score": "...", "rank": "...", "errors": ["..."] },
  "consultant_C": { "accuracy_score": "...", "rank": "...", "errors": ["..."] },
  "best_report": "<consultant_A|consultant_B|consultant_C>"
}
```

Each consultant's `errors` array must list every incorrect finding in their report. The `rank` field orders consultants from 1 (most accurate) to 3 (least accurate). `best_report` names the consultant with the highest accuracy.

### `/app/corrected_diagnosis.json`

The definitive correct analysis with all metrics independently computed from the raw incident data:

```json
{
  "buffer_cache": {
    "hit_ratio": "<float>",
    "current_size_mb": "<int>",
    "recommended_size_mb": "<int>",
    "status": "<undersized|adequate|oversized>"
  },
  "library_cache": {
    "hit_ratio": "<float>",
    "reloads": "<int>",
    "hard_parse_ratio": "<float>",
    "root_cause": "<literal_sql|insufficient_shared_pool|ddl_invalidation>"
  },
  "pga": {
    "current_target_mb": "<int>",
    "recommended_target_mb": "<int>",
    "cache_hit_pct": "<float>",
    "multipass_ratio": "<float>",
    "overalloc_count": "<int>"
  },
  "top_wait_events": [
    {"event": "<name>", "time_waited_s": "<float>"}
  ],
  "problematic_sql": {
    "sql_id": "<id>",
    "buffer_gets_per_exec": "<float>",
    "disk_reads_per_exec": "<float>",
    "issue": "<full_table_scan|bad_index|cartesian_join>",
    "missing_index_columns": ["<col>", "..."]
  },
  "root_causes_ranked": ["<most impactful first>", "..."]
}
```

`top_wait_events`: the 3 most impactful non-Idle-class wait events, ordered by total time waited. `problematic_sql`: the most resource-inefficient point query (high per-execution cost relative to rows returned). `root_causes_ranked`: at least 3 root causes, ordered by the total time impact of their correlated wait events.

### `/app/remediation.sql`

Oracle SQL remediation script addressing all identified root causes. Must include:
- `ALTER SYSTEM SET ... SCOPE=BOTH` commands for memory allocation parameters (buffer cache sizing, PGA target) and cursor sharing behavior
- `CREATE INDEX` statement(s) for missing indexes on the problematic query's predicate columns, referencing the correct table