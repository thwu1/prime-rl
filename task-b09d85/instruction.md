A PostgreSQL 16 database (`appdb`) at `/app` is managed by Atlas versioned migrations. The system is in a degraded state following a deployment incident compounded by ad-hoc operator intervention and a botched feature-branch merge.

**Incident history:** The `/app/migrations/` directory contains migration files for versions 1 through 5. Migrations 1 and 2 were applied successfully. Migration 3 (`20240101000003_categories_shipping.sql`) was deployed with `--tx-mode none` and partially failed at statement 4 — an `ALTER TABLE orders ADD COLUMN shipping_address VARCHAR(500) NOT NULL` that could not complete against a table with existing rows. An on-call operator then manually patched the schema, but their changes deviate from the migration specification and they created additional database objects that are not defined in any migration file.

**Merge conflict:** Two feature branches were merged that both created migration version 4 — the directory contains two files with version `20240101000004`. One adds `phone` as nullable, the other as `NOT NULL`. The migration directory's integrity file (`atlas.sum`) is missing.

Migration 5 has never been applied. Pending migrations may contain SQL that will not execute successfully against the current data state — you must evaluate each for correctness, fix any defects, and ensure the migration directory is internally consistent.

Atlas configuration is at `/app/atlas.hcl`. PostgreSQL is installed but not running. Trust authentication is configured for user `postgres`. A dev database `appdb_dev` is available.

**Objective:** Restore the database to a fully consistent, Atlas-managed state:
- The duplicate version conflict in the migration directory is resolved (keep the stricter `NOT NULL` variant for `phone`)
- All five migrations are recorded as successfully applied in Atlas revision tracking
- The live schema exactly matches the state defined by the complete migration directory
- No database objects exist outside what the migrations define
- All pre-existing data (users, products, orders, order_items) is preserved
- The migration directory's integrity file (`atlas.sum`) is consistent with the migration files