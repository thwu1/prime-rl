A PostgreSQL database is running at localhost:5432 (database: `ecommerce`, user: `admin`, password: `taskpass`). It powers an e-commerce platform whose previous DBA added indexes aggressively over time and left without documentation. The database now suffers from degraded write throughput due to index bloat, while certain critical reporting queries remain slow because they lack appropriate index support.

The database has `pg_stat_statements` enabled with accumulated workload statistics, and `pg_stat_user_indexes` reflects the application's actual usage patterns.

Perform a comprehensive index audit of the database. Identify all index-related problems — including duplicate indexes, unused indexes, indexes made redundant by B-tree left-prefix coverage, and missing indexes for slow query patterns — and produce an optimized SQL migration at `/app/migration.sql`. Execute the migration against the running database.

Constraints:
- Never drop indexes that enforce uniqueness or primary key constraints, even if they show low scan counts
- Never drop indexes that are actively used by the application's query patterns (consult scan statistics)
- Address slow query patterns revealed by `pg_stat_statements` analysis
- Apply B-tree left-prefix coverage rules when assessing index redundancy
- Consider partial indexes where data distribution is heavily skewed