A PostgreSQL 16 database serves an e-commerce application with three tables: `orders` (~300K rows), `order_items` (~600K rows), and `audit_log` (~100K rows). Users report progressively slower queries and unexpected storage growth consistent with table bloat. Running `VACUUM` manually has no effect — dead tuples remain. The `pgstattuple` extension is installed.

Investigate the PostgreSQL instance to determine why dead tuples are accumulating despite autovacuum being enabled globally. There are multiple independent root causes — find and fix all of them. Then tune the vacuum subsystem for optimal performance on this workload.

After your changes, the following conditions must all be met:

**Vacuum Blockers**
- No orphaned prepared transactions may exist (`pg_prepared_xacts` must return zero rows)
- Autovacuum must not be explicitly disabled (`autovacuum_enabled=false`) in any table's `reloptions`

**Per-Table Tuning**
- `autovacuum_vacuum_scale_factor` must be set below `0.05` via per-table `reloptions` on each of `orders`, `order_items`, and `audit_log`

**Global Vacuum Configuration (via `ALTER SYSTEM SET`)**
- `autovacuum_vacuum_cost_delay` must be `5ms` or less
- `autovacuum_vacuum_cost_limit` must be `200` or greater
- `maintenance_work_mem` must be `256MB` or greater
- `idle_in_transaction_session_timeout` must be set to a non-zero value to prevent future vacuum-blocking idle transactions

**Bloat Remediation**
- Dead tuple percentage must be below 5% on all three tables (verified via `pgstattuple`)

**Configuration File**
- Write your final global vacuum configuration to `/app/postgresql_tuning.conf` (one `parameter = value` per line), containing at minimum these four parameters: `autovacuum_vacuum_cost_delay`, `autovacuum_vacuum_cost_limit`, `maintenance_work_mem`, `idle_in_transaction_session_timeout`

**Vacuum Health Monitoring Function**

Create a PL/pgSQL function `public.vacuum_health_report()` in the `postgres` database that serves as a reusable vacuum health diagnostic. It must:

- Return columns: `check_name TEXT`, `status TEXT`, `current_value TEXT`, `recommended_action TEXT`
- Use only these status values: `OK`, `WARNING`, `CRITICAL`
- Return at least 8 distinct `check_name` values covering the full range of vacuum pathologies you discovered and fixed during your investigation
- After all remediations are applied, the function must return zero rows with `status = 'CRITICAL'`

Start PostgreSQL with `pg_ctlcluster 16 main start`. Connect with `psql -U postgres`.