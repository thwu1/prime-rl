The PostgreSQL environment contains two SQL scripts for estimating storage bloat from catalog statistics:

- `/app/bloat_estimate.sql` -- estimates heap table bloat from `pg_class`, `pg_stats`, and `pg_attribute`
- `/app/index_bloat_estimate.sql` -- estimates B-tree index bloat from the same catalogs

Both scripts contain multiple bugs in their storage-layer constants and arithmetic that cause inaccurate bloat estimates. A PostgreSQL 16 instance with `pgstattuple` enabled is available for ground-truth validation via `pgstattuple()` (tables) and `pgstatindex()` (B-tree indexes). Fix both scripts so they produce accurate results.

Additionally, create `/app/vacuum_advisory.sql` that defines a PL/pgSQL function with this exact signature:

```sql
CREATE OR REPLACE FUNCTION vacuum_advisory(p_schema TEXT DEFAULT 'public')
RETURNS TABLE (
    table_name TEXT,
    table_size_bytes BIGINT,
    estimated_bloat_pct DOUBLE PRECISION,
    dead_tuple_count BIGINT,
    dead_tuple_pct DOUBLE PRECISION,
    max_index_bloat_pct DOUBLE PRECISION,
    last_vacuum TIMESTAMPTZ,
    last_autovacuum TIMESTAMPTZ,
    recommendation TEXT
)
```

The function must:

- Internally compute table bloat estimates using corrected catalog-based logic (not pgstattuple)
- Compute per-table maximum B-tree index bloat percentage using corrected catalog-based logic
- Retrieve dead tuple statistics from `pg_stat_user_tables`
- Compute `dead_tuple_pct` as `100.0 * n_dead_tup / (n_live_tup + n_dead_tup)` (0 when no tuples)
- Return one row per table in the given schema, ordered by `table_name`
- Assign `recommendation` following these priority rules (first match wins):
  1. `'VACUUM FULL'` when `estimated_bloat_pct > 50`
  2. `'REINDEX'` when `max_index_bloat_pct > 30` AND `estimated_bloat_pct <= 50`
  3. `'VACUUM'` when `estimated_bloat_pct > 20` OR `dead_tuple_pct > 5`
  4. `'OK'` otherwise

**Verification**: Test tables with varying bloat levels will be created. For tables where actual wasted space exceeds one page, estimated bloat must fall within 15 percentage points of `pgstattuple`-reported wasted space. Default fillfactor must be 100 for tables and 90 for B-tree indexes. The `vacuum_advisory` function must return correct columns, consistent recommendations matching the priority rules, and expected outcomes for known bloat scenarios.
