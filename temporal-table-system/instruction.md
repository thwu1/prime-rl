A temporal versioning system for PostgreSQL is partially implemented at `/app/temporal.sql`. It provides automatic point-in-time history tracking via the `temporal` schema and a `temporal.tracked_tables` registry. The current implementation contains bugs that cause incorrect results in several scenarios.

Run `/app/setup.sh` to initialize the `temporal_test` database with the schema from `/app/seed.sql` and the current functions. Investigate failures and fix all bugs in `/app/temporal.sql`.

Additionally, implement `temporal.merge_history`, which is currently a stub.

**Required behavior when correct:**

`temporal.enable_versioning(target_table regclass)` — Creates `<table>_history` in the same schema with all original columns plus `_valid_from timestamptz` and `_valid_to timestamptz`. Installs a per-row trigger capturing every INSERT, UPDATE, and DELETE: live history records have `_valid_to = 'infinity'`; modifications close the prior record and insert a new live record. Rows present at enablement time must appear as initial history. Registers the table in `temporal.tracked_tables`. Raises an exception if the table lacks a primary key or is already tracked.

`temporal.disable_versioning(target_table regclass)` — Drops the history table, removes the change-capture trigger, and deletes the registry entry. Raises an exception if the table is not currently tracked.

`temporal.table_at(target_table regclass, ts timestamptz) RETURNS SETOF jsonb` — Returns every row valid at `ts` as JSONB keyed by original column names only (no temporal metadata). A row is valid when `_valid_from <= ts AND _valid_to > ts`.

`temporal.changes_between(target_table regclass, ts1 timestamptz, ts2 timestamptz) RETURNS TABLE(operation text, pk_values jsonb, old_row jsonb, new_row jsonb)` — Compares reconstructed states at `ts1` and `ts2`. One row per changed entity: `'INSERT'` (`old_row` NULL), `'UPDATE'`, or `'DELETE'` (`new_row` NULL). Unchanged entities must not appear.

`temporal.merge_history(target_table regclass) RETURNS integer` — Compacts the history table by merging adjacent records for the same entity whose non-temporal column values are identical. Two records are adjacent when one's `_valid_to` equals the next's `_valid_from`. Chains of three or more identical consecutive records must collapse into one. Returns the number of records removed.

All functions must correctly handle single-column and composite primary keys.

**Success criteria:** `/app/temporal.sql` loads without errors into `temporal_test` and all tests pass.
