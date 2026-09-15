A production Oracle 19c OLTP database is suffering severe performance degradation. Diagnostic data exported from Oracle V$ dynamic performance views is available as static files in `/app/diagnostic_data/`. No running Oracle instance is available — all analysis must be performed against these exported files.

## Data Files

`/app/diagnostic_data/` contains: `v_sysstat.csv` (V$SYSSTAT), `v_db_cache_advice.csv` (V$DB_CACHE_ADVICE), `v_pga_target_advice.csv` (V$PGA_TARGET_ADVICE), `v_librarycache.csv` (V$LIBRARYCACHE), `v_system_event.csv` (V$SYSTEM_EVENT), `v_pgastat.csv` (V$PGASTAT), `v_sgastat.csv` (V$SGASTAT), `v_parameter.csv` (V$PARAMETER), `alert_log.txt`, `top_sql.csv`, and `schema_info.txt`.

## Required Output

Generate `/app/tuning_report.json`:

```json
{
  "metrics": {
    "buffer_cache_hit_ratio": "<float 0-1>",
    "library_cache_hit_ratio": "<float 0-1, pinhits/pins across all namespaces>",
    "hard_parse_ratio": "<float 0-1>",
    "in_memory_sort_ratio": "<float 0-1>",
    "pga_cache_hit_pct": "<float 0-100>",
    "shared_pool_free_pct": "<float 0-100, free memory as pct of total shared pool>"
  },
  "optimal_db_cache_size_mb": "<int: smallest size where estd_physical_read_factor <= 0.50>",
  "optimal_pga_target_mb": "<int: smallest PGA target where estd_overalloc_count == 0>",
  "top_wait_events": [
    {"event": "<name>", "time_waited_seconds": "<float>"}
  ],
  "recommendations": [
    {
      "rank": "<int, 1=highest priority>",
      "parameter": "<Oracle init parameter>",
      "current_value": "<string>",
      "recommended_value": "<string>"
    }
  ]
}
```

`top_wait_events`: top 5 non-idle wait events ordered by total time waited descending, times converted from microseconds to seconds (exclude wait_class "Idle").

`recommendations`: at least 4 ranked parameter changes derived from Oracle's standard metric formulas. The highest-priority recommendation must address the dominant bottleneck identified by correlating wait events, system statistics, and alert log evidence.