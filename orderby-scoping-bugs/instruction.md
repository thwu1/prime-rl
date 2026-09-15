A PostgreSQL 16 database `benchdb` (user `postgres`, trust auth) contains a `transactions` table (schema at `/app/schema.sql`). Ten SQL query files at `/app/queries/q1.sql` through `/app/queries/q10.sql` exercise various ORDER BY patterns. Some of these queries contain subtle bugs that cause them to produce incorrect results or errors; others are correct and must not be modified.

## Deliverables

1. **Evaluate** each query by running it against the database and comparing its output to the corresponding file in `/app/expected/` (pipe-delimited, no headers, generated with `psql -t -A -F '|'`). Determine whether each query is buggy or correct.

2. **Fix** each buggy query in-place so its output matches the expected file. Do not alter correct queries, `/app/schema.sql`, or anything under `/app/expected/`.

3. **Create** `/app/diagnostic.json` — a JSON object with a `queries` array of exactly 10 entries, each containing:
   - `query` (integer 1–10): query number
   - `status` (string): `"buggy"` or `"correct"`
   - `category` (string): the root cause category for buggy queries, or `"none"` for correct queries

### Valid bug categories

`alias_shadow`, `group_order_precedence`, `quoted_case`, `window_scope`, `union_expression`, `collate_expression`, `unary_expression`

Each buggy query falls into exactly one of these categories. Investigate PostgreSQL's ORDER BY identifier resolution behavior to determine which category applies to each bug.

PostgreSQL is installed but not running; start it with `pg_ctlcluster 16 main start`.