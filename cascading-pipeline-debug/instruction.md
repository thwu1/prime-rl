A production CDN platform at `/app/` has multiple services failing after a routine database infrastructure change to `/app/data/pipeline.db`.

**Symptoms:**
- The ML feature config loader (`/app/bin/config_loader`) crashes on startup
- The prefix manager (`/app/bin/prefixmgr`) is incorrectly deleting active customer IP prefixes during periodic `cleanup` — not just those marked for removal

**System layout:**
- Config generator: `/app/configgen/generate.py` → `/app/config/features.json`
- Config loader: `/app/loader/` (Rust source, binary at `/app/bin/config_loader`)
- Prefix manager: `/app/prefixmgr/` (Go source, binary at `/app/bin/prefixmgr`)
- Pipeline database: `/app/data/pipeline.db` (SQLite)
- Prefix data: `/app/data/prefixes.json`

**Required outcomes:**

1. Root-cause the full failure cascade from the infrastructure change through every affected component. Fix all bugs and rebuild binaries so the end-to-end pipeline (generate → load config) works and prefix cleanup targets only `pending_delete` prefixes.

2. Add a bulk-deletion circuit breaker to the prefix manager: `cleanup` must refuse (exit non-zero) when it would delete more than 50% of total prefixes in a single run. No data should be modified when triggered.

3. Create `/app/validate_pipeline.py` — a pre-deployment integrity validator that exits 0 when healthy and exits 1 with diagnostics otherwise. It must detect duplicate entries and configs exceeding the system's feature limit.

All modified source must be rebuilt into working binaries.