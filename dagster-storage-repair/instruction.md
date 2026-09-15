A data orchestration system at `/app/` uses a SQLite storage backend (`/app/dagster_storage.db`) that has degraded after months of operation. The daemon's recent error and performance log is at `/app/daemon_log.txt`. The system's schema, data integrity invariants, and behavioral contracts are documented in `/app/ARCHITECTURE.md`.

Diagnose all issues by cross-referencing the daemon log against the architecture document and the actual database state, then produce four deliverables:

- **`/app/repair_db.py`** — Restore all violated data integrity invariants documented in ARCHITECTURE.md. Requires identifying which invariants are violated by querying the database and matching against the documented constraints.
- **`/app/optimize_db.py`** — Add indexes so every query in `/app/queries.py` uses an indexed lookup (no full table scans). The seven queries have diverse filter, sort, and aggregation patterns — some share columns but require different index column orderings. Verify via `EXPLAIN QUERY PLAN`.
- **`/app/retention.py`** — Implement the full retention policy from ARCHITECTURE.md including all four preservation carve-outs (latest materializations, non-terminal runs, backfill-tagged runs, tick top-3 retention). Must be safe to run after repair.
- **`/app/pipeline/reconciliation.py`** — Fix all bugs in the asset reconciliation module. The daemon log identifies five distinct failure modes. The module's docstrings describe intended behavior — compare against actual implementation to identify each defect.

The query workload in `/app/queries.py` documents the daemon's hot-path queries. The reconciliation module at `/app/pipeline/reconciliation.py` contains the buggy code to fix in place.