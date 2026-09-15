A column-store join query pipeline in `/app/` was recovered after a storage failure. The recovery left inconsistencies across data sources and potential corruption in the query engine itself.

For each of six relations (`r0` through `r5`), three independent data representations exist:
- Binary column-store files in `/app/data/` (`.bin`)
- CSV backup exports in `/app/data/` (`.csv`)
- A SQLite catalog database at `/app/catalog.db` (tables `r0` through `r5`)

No single representation is universally reliable — some binary files, some CSV exports, and some SQLite tables were damaged during recovery. At least one corruption exists where no two representations agree, requiring deeper forensic comparison to identify the trustworthy source. The query engine at `/app/engine.py` also contains semantic defects independent of any data corruption.

The binary format and query DSL are documented in `/app/README.md`. Tools available include `sqlite3`, `xxd`, and Python 3 with the `struct` and `csv` modules.

Determine the ground-truth data for every relation by cross-validating all three sources, identify and correct any engine defects, and produce `/app/output.txt` — one line per query from `/app/workload.txt` containing space-separated SUM values, or `NULL` for each projection column when no tuples qualify.