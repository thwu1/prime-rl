Build a catastrophe model financial module pipeline at `/app/`. The pipeline reads ground-up losses, applies insurance financial terms through a multi-level hierarchical aggregation structure, and produces three output artifacts via a Makefile-orchestrated build.

**Execution**: `make -C /app all` must produce all outputs below from a clean state. `make -C /app clean` must remove all generated artifacts. Running `make -C /app clean && make -C /app all` must be idempotent.

**Required outputs:**

`/app/output.csv` — Per-item insured losses: columns `event_id,item_id,sidx,loss`. Losses rounded to 2 decimal places. Sorted by `event_id`, then `item_id`, then `sidx`. Exclude rows where rounded loss equals zero.

`/app/fm_results.db` — SQLite database containing:

- Table `level_losses` with columns `event_id INTEGER, sidx INTEGER, level INTEGER, agg_id INTEGER, input_loss REAL, output_loss REAL`. One row per aggregation node per event/sample, recording the node's aggregated input and post-calcrule output at each hierarchy level.
- Table `final_losses` with columns `event_id INTEGER, item_id INTEGER, sidx INTEGER, loss REAL`. Per-item final insured losses (positive values only, rounded to 2 decimal places).
- View `event_summary` returning columns `event_id, total_gul, total_insured, item_count, reduction_pct`. `total_gul`: sum of all ground-up losses for the event across all items and samples. `total_insured`: sum of final losses for that event. `item_count`: count of distinct items with at least one positive final loss entry for that event. `reduction_pct`: `ROUND(100.0 * (1.0 - total_insured / total_gul), 2)`.

`/app/report.json` — JSON array of per-event summary objects sorted by `event_id`:
```json
[{"event_id": 1, "total_gul": ..., "total_insured": ..., "item_count": ..., "reduction_pct": ...}]
```
Values must be consistent with the `event_summary` view.

**Input data** in `/app/data/`: `fm_programme.csv`, `fm_profile.csv`, `fm_policytc.csv`, `guls.csv`.

**Specifications** in `/app/docs/`: `calcrules.md` documents all calculation rule formulas. `fm_architecture.md` documents the hierarchical computation model including level-by-level aggregation, calcrule application, and proportional back-allocation semantics.
