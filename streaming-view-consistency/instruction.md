A financial streaming pipeline at `/app/` processes timestamped transactions and maintains materialized views (per-account credits, debits, balances). An internal audit flagged consistency violations — the sum of balances deviates from zero at intermediate checkpoints, and other anomalies emerge under different watermark delay configurations. Transaction data is at `/app/data/`. A diagnostic log from the last run is at `/app/logs/diagnostic.log`. DuckDB and `jq` are pre-installed.

When the task is complete, the following must all be true:

- A batch reference oracle exists at `/app/oracle/`, invocable via `/app/oracle/compute.sh <watermark_delay>`, that writes `/app/oracle/batch_results.json` containing: `watermark_delay`, `accepted_count`, `rejected_count`, `credits`, `debits`, `balance`, `total`. The oracle must use DuckDB for its computations.

- A consistency monitor exists at `/app/monitor/` that writes `/app/monitor/report.json` with schema: `systems` (list of `{watermark_delay, consistent, total_anomalies, failure_modes}` per delay for delays `[0, 1, 5, 10, 20]`), `overall_consistent` (bool). Valid `failure_modes` values: `stream_desync`, `watermark_boundary`, `missing_accounts`, `finalization_error`. The monitor must use `jq` and reference the oracle.

- The streaming pipeline achieves internal consistency: `total == 0` at every checkpoint, `balance[account] == credits[account] - debits[account]` for all accounts, across all watermark delays. The monitor report shows `overall_consistent: true` with zero anomalies at every delay.