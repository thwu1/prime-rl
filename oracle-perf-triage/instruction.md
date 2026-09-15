An Oracle 19c production OLTP database (`PRODDB`, 12.5M+ row transactional schema) experienced severe performance degradation during peak hours. A junior DBA exported diagnostic data from Oracle dynamic performance views and Statspack into a SQLite database and produced a preliminary analysis. The team suspects calculation errors, missed issues, and incorrect conclusions in that analysis.

The SQLite database at `/app/data/perfdata.db` contains tables derived from Oracle V$ views: `sysstat`, `db_cache_advice`, `librarycache`, `pgastat`, `pga_target_advice`, `system_event`, `sqlarea`, `parameter`, `segment_statistics`, `waitstat`, `sgastat`. Execution plan output is at `/app/data/explain_plans/`, a Statspack snapshot report at `/app/data/statspack_summary.txt`, and the prior DBA's analysis at `/app/data/prior_analysis.json`.

**WARNING**: The data loading process may have introduced anomalies. Validate data quality before relying on query results.

The database exhibits degradation across buffer cache efficiency, SQL parsing behavior, PGA memory allocation, segment-level concurrency, and SQL execution plan quality. Audit the prior analysis for correctness, detect data quality issues, independently compute all performance metrics, and produce the following output files in `/app/output/`:

**`/app/output/metrics.json`** — JSON object with keys: `buffer_cache_hit_ratio` (float, 0-1), `library_cache_hit_ratio` (float, 0-1), `soft_parse_ratio` (float, 0-1), `recommended_db_cache_size_mb` (integer), `recommended_pga_target_mb` (integer). All values independently derived from database tables.

**`/app/output/findings.json`** — JSON array of identified performance issues. Each element must include `description` and `root_cause` fields. Analysis must comprehensively cover all major problem areas evident in the data. Findings should reference specific Oracle parameters, objects, and metrics.

**`/app/output/remediation.sql`** — Syntactically valid Oracle SQL commands (`ALTER SYSTEM SET`, `CREATE INDEX`, etc.) addressing each identified root cause, with parameter values derived from advisory and diagnostic data.

**`/app/output/audit_report.json`** — JSON object with:
- `prior_findings_assessment`: array of objects, one per finding in the prior report, each with `finding_id` (matching prior report), `verdict` (`correct`, `incorrect`, or `partially_incorrect`), and `explanation`.
- `missed_issues`: array of objects for issues the prior analyst missed, each with `category` and `description`.
- `data_anomalies`: array of objects for data quality problems found, each with `description`.