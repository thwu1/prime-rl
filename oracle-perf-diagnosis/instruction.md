A production Oracle 19c OLTP system experienced severe performance degradation during a 1-hour peak window. Two senior DBAs independently analyzed the same raw diagnostic data and reached conflicting conclusions about the root cause and remediation.

Raw data exports from Oracle V$ dynamic performance views are at `/app/perfdata/`:

- `sysstat_begin.csv` / `sysstat_end.csv` — V$SYSSTAT cumulative counter snapshots (beginning and end of interval)
- `time_model.csv` — V$SYS_TIME_MODEL (microseconds)
- `system_events.csv` — V$SYSTEM_EVENT wait event statistics
- `db_cache_advice.csv` — V$DB_CACHE_ADVICE buffer cache sizing advisory
- `pga_target_advice.csv` — V$PGA_TARGET_ADVICE memory advisory
- `sql_stats.csv` — V$SQL execution statistics
- `shared_pool_stats.csv` — Library cache and dictionary cache statistics
- `parameters.csv` — Current initialization parameter settings

The two competing reports are at `/app/reports/report_a.json` and `/app/reports/report_b.json`. Both contain computed metrics, sizing recommendations, SQL tuning analysis, and a primary bottleneck classification — but each contains errors of varying severity.

Serve as a peer reviewer: independently derive the correct metrics and recommendations from the raw data, then evaluate each report's accuracy claim-by-claim. Determine which report is more reliable overall.

Required deliverables:

- `/app/audit.db` — SQLite database with all raw CSV data loaded into queryable tables
- `/app/diagnosis/db_cache_advisory.png` — Buffer cache advisory curve chart produced by gnuplot
- `/app/diagnosis/pga_advisory.png` — PGA target advisory curve chart produced by gnuplot
- `/app/diagnosis/results.json` — Peer review output with the structure below

```json
{
  "metrics": {
    "buffer_cache_hit_ratio": <float>,
    "library_cache_hit_ratio": <float>,
    "soft_parse_ratio": <float>,
    "in_memory_sort_ratio": <float>,
    "execute_to_parse_ratio": <float>,
    "db_time_cpu_pct": <float>,
    "db_time_wait_pct": <float>
  },
  "memory_recommendations": {
    "db_cache_size_mb": <int>,
    "pga_aggregate_target_mb": <int>
  },
  "wait_analysis": {
    "top_event": "<string>",
    "top_event_time_sec": <float>,
    "total_wait_time_sec": <float>
  },
  "sql_tuning": {
    "top_sql_by_elapsed": ["<sql_id>", ...],
    "literal_sql_ids": ["<sql_id>", ...],
    "cursor_sharing": "<FORCE|EXACT>"
  },
  "primary_bottleneck": "<string>",
  "report_evaluation": {
    "report_a": {
      "accuracy_score": <float 0-1>,
      "incorrect_claims": ["<field_name>", ...]
    },
    "report_b": {
      "accuracy_score": <float 0-1>,
      "incorrect_claims": ["<field_name>", ...]
    },
    "better_report": "<A|B>"
  }
}
```

All performance metrics are ratios in [0, 1]. Memory recommendations should reflect optimal sizing from the advisory data. `primary_bottleneck` is one of: `buffer_cache`, `shared_pool`, `pga`, `cpu`, `io`, `redo`, `latch`, `lock`. Top SQL is ordered by elapsed time descending (top 3). Use the field names from the structure above when listing incorrect claims (e.g., `"buffer_cache_hit_ratio"`, `"db_cache_size_mb"`).