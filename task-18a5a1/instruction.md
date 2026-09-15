A column-store database at `/app/` was corrupted during a failed schema migration. The binary relation files in `/app/data/` have distinct structural and encoding defects that must be identified and repaired before the analytical queries can produce correct results.

A post-crash diagnostic report is at `/app/crash_report.txt`. Be aware that crash-time state captures can be unreliable — always verify hypotheses against the actual binary data. The intact reference file `r0` demonstrates the canonical binary layout. Schema constraints are in `/app/schema.sql`.

Some corruptions have no diagnostic metadata available; they must be identified entirely through binary analysis of the affected files and cross-referencing with the expected schema.

Diagnose each corruption, repair the affected binary files in-place under `/app/data/`, and execute the queries from `/app/queries.sql` against the repaired data.

Write all query results to `/app/output.txt` — one line per query, space-separated column values, or `NULL` for empty result sets.

Create `/app/repair.sh` that performs the complete recovery and query execution pipeline.