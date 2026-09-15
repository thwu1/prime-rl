A SQLite database at `/app/analytics.db` serves a retail analytics platform. An interrupted schema migration corrupted data and metadata. A DBA then attempted manual repairs, introducing additional problems. A pre-DBA-intervention snapshot is available at `/app/analytics.db.bak`.

Diagnose all issues and produce an idempotent repair script at `/app/repair.sql`, executable via `sqlite3 /app/analytics.db < /app/repair.sql`.

## Schema

Tables: `users`, `categories` (self-referencing via `parent_id`), `products`, `orders`, `order_items`, `reviews`, `events`.
Views: `monthly_revenue`, `product_best_review`.
System table: `sqlite_stat1` (query planner statistics).

## Observed anomalies

- The `monthly_revenue` view produces incorrect results: although each row's `total_revenue` figure is non-zero, the `product_id` and `product_name` columns do not match the products that actually generated that revenue. Investigate the view definition to understand why.

- A recursive CTE walking the `categories` hierarchy from root nodes (`parent_id IS NULL`) reaches only 15 of 20 categories. Compare the live database with the backup to understand what the DBA changed and why the hierarchy is still broken.

- The `product_best_review` view returns the correct `best_rating` for each product, but the `reviewer_id`, `best_comment`, and `review_date` columns come from the wrong review row. Investigate the view definition to determine why the detail columns are misaligned.

- `PRAGMA foreign_key_check` reports violations across multiple tables. Investigate which referenced rows are missing and why. Note that some of the DBA's repair attempts may have introduced new violations.

- `events.occurred_at` contains values in multiple inconsistent formats. Date-range queries using string comparison return incorrect results. All dates must be normalized to ISO-8601 (`YYYY-MM-DD HH:MM:SS`).

- The `sqlite_stat1` table contains statistics that do not match actual table sizes. Query planner behavior is unreliable as a result.

## Constraints

- The script must be valid SQLite SQL and idempotent (safe to execute more than once).
- Do not delete rows from `orders`, `order_items`, `reviews`, or `events`.
- Post-repair: `PRAGMA foreign_key_check` must report zero violations; `PRAGMA integrity_check` must return `ok`.
- Preserve row counts: 20 categories, 500 orders, 600 order_items, 1000 events.
- `monthly_revenue` must show per-(month, product) revenue figures that match actual `order_items` aggregates.
- `product_best_review` detail columns must correspond to the actual highest-rated review for each product.
- `sqlite_stat1` must contain accurate statistics consistent with actual table sizes.