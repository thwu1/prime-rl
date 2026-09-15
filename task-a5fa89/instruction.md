A SQLite database file at `/app/evidence.db` was recovered from a crashed trading compliance server. The file has sustained multiple binary corruptions — in the 100-byte file header and within B-tree page structures — and cannot be opened. The original database used a non-default page size that must be deduced from structural evidence in the file.

The database contains four tables (`traders`, `instruments`, `trades`, `compliance_flags`) with trading and compliance data across 2000+ trade records and 300 compliance flags.

After repairing the file so it passes `PRAGMA integrity_check` with all data intact, evaluate three candidate index strategies that were proposed by different team members for optimizing the compliance workload. The strategy SQL files are in `/app/candidate_strategies/` (`strategy_a.sql`, `strategy_b.sql`, `strategy_c.sql`). Each contains CREATE INDEX statements intended to optimize the queries in `/app/target_queries.sql`.

For each candidate strategy, determine whether it successfully eliminates all full table scans (`SCAN`) on the `trades` and `compliance_flags` tables across every target query. Identify which queries (numbered 1–5) still require full scans under each strategy and assess why the strategy succeeds or fails.

Then design your own index strategy that satisfies all of the following:
- Uses no more than 4 user-created indexes
- Eliminates all full table scans on `trades` and `compliance_flags` for every target query
- Is more storage-efficient than any candidate strategy that also achieves zero full scans (fewer total indexed columns)

Write your competitive evaluation and designed strategy to `/app/analysis.json`:
```
{
  "strategy_a": {"has_full_scans": <bool>, "full_scan_queries": [<int>, ...], "assessment": "<text>"},
  "strategy_b": {"has_full_scans": <bool>, "full_scan_queries": [<int>, ...], "assessment": "<text>"},
  "strategy_c": {"has_full_scans": <bool>, "full_scan_queries": [<int>, ...], "assessment": "<text>"},
  "designed_strategy": {"indexes": ["CREATE INDEX ...", ...], "rationale": "<text>"}
}
```

Apply your designed strategy to the repaired database and run `ANALYZE`. The final optimized database must remain at `/app/evidence.db`.