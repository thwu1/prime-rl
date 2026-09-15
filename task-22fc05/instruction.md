An e-commerce platform at `/app/` has 15 tables across 8 shards. The system is migrating from a legacy random-assignment sharding scheme to Vitess (horizontal sharding middleware for MySQL). Legacy records (IDs at or below a per-table threshold) have historical shard mappings stored in SQLite. New records (above threshold) must be routed using the algorithm implemented in the Go reference source.

## Data Files

- `/app/shard_config.json` — Shard range definitions with hex keyspace ID boundaries
- `/app/table_config.json` — Per-table shard key column, legacy threshold, and record count
- `/app/legacy_mappings.db` — SQLite database with table `shard_map(table_name, record_id, shard_number)`
- `/app/transaction_log.jsonl` — Production write transactions (some span multiple tables)
- `/app/query_workload.jsonl` — SQL queries to classify
- `/app/reference/vindex_hash.go` — Go source of the authoritative shard routing algorithm

## Required Outputs (write to `/app/output/`)

**`hybrid_router.py`** — Python module exporting:
- `vhash(shard_key: int) -> bytes` — Produces the same 8-byte keyspace ID as the Go reference for any integer input, including negative values
- `route_id(table_name: str, record_id: int) -> int` — Returns shard number 0–7: legacy records route via the SQLite mappings, new records route via the hash algorithm against the configured shard ranges

**`migration_plan.json`**:
- `coupled_groups` — Groups of tables that share multi-table write transactions and therefore must be migrated as atomic units; tables with no cross-table writes form singleton groups
- `migration_order` — Ordered list of groups for incremental migration

**`conflict_report.json`**:
- `per_table` — For each table: `{"conflicts": N, "total": N, "conflict_rate": float}` counting legacy records whose current shard placement differs from where the hash algorithm would route them
- `overall_conflict_rate` — Weighted average conflict rate across all tables (weighted by each table's legacy record count)

**`vschema.json`** — Vitess VSchema configuration with `sharded: true`, a hash-type vindex definition, and all 15 tables mapped with their correct shard key columns from the table configuration

**`scatter_analysis.json`** — For each query in the workload: `{"query_id": "...", "is_scatter": bool}` — true when the query's filter predicates are insufficient for the routing layer to target a specific shard