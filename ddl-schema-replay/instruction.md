A PostgreSQL 16 database contains a table `ddl_history` loaded from `/app/seed.sql`. This table has columns `(seq_id SERIAL, ddl_text TEXT)` and holds 25 MySQL DDL statements in execution order, representing a production database schema's evolution as captured by a CDC system.

Write `/app/reconstruct.sql` — a SQL script that, when executed against this database, creates and populates a `schema_state` table with the final column metadata for every surviving table after all DDL statements have been applied in order. A skeleton exists at `/app/reconstruct.sql` with the required table definition.

Required `schema_state` schema:
```sql
CREATE TABLE schema_state (
  table_name TEXT NOT NULL,
  column_name TEXT NOT NULL,
  ordinal_position INT NOT NULL,
  data_type TEXT NOT NULL,
  is_nullable BOOLEAN NOT NULL,
  column_default TEXT,
  is_primary_key BOOLEAN NOT NULL,
  is_generated BOOLEAN NOT NULL DEFAULT FALSE,
  PRIMARY KEY (table_name, column_name)
);
```

The MySQL DDL statements cannot be executed on PostgreSQL — they must be parsed as text. They include: backtick-quoted identifiers, `ENUM`/`SET` types with value lists, inline `CHARACTER SET`/`COLLATE`, `COMMENT` clauses, function-call defaults (`json_object()`, `current_timestamp()`, `UUID()`, `curtime()`, `CURRENT_TIMESTAMP(6)`), expression defaults wrapped in parentheses, `GENERATED ALWAYS AS (expr) STORED/VIRTUAL`, `AUTO_INCREMENT`, `ON UPDATE CURRENT_TIMESTAMP`, `IF EXISTS`/`IF NOT EXISTS`, `FIRST`/`AFTER col` position modifiers, SQL reserved words as table/column names, and multiple operations in a single `ALTER TABLE`.

Value rules for `schema_state`:
- **data_type**: lowercase, include length/precision and `unsigned` (e.g. `varchar(100)`, `bigint unsigned`, `enum('A','B')`). Exclude `CHARACTER SET`/`COLLATE`.
- **column_default**: string literal defaults without surrounding quotes; numerics as-is; function/keyword expressions preserved as-is (e.g. `CURRENT_TIMESTAMP`); expression defaults `(expr)` stored without outer parentheses. SQL `NULL` for no default, explicit `DEFAULT NULL`, `AUTO_INCREMENT`, or generated columns.
- **is_generated**: `TRUE` for `GENERATED ALWAYS AS` columns.
- **ordinal_position**: final column order accounting for `FIRST`/`AFTER` effects and column drops.
- **is_nullable**: `MODIFY COLUMN` redefines the column completely — attributes not restated revert to defaults (nullable without explicit `NOT NULL`, no default without explicit `DEFAULT`).
- Dropped tables must not appear. Renamed tables/columns appear under their new name.

The test infrastructure handles PostgreSQL startup and seed loading. After `/app/reconstruct.sql` executes, `schema_state` must contain exactly the expected rows — no extra, no missing.
