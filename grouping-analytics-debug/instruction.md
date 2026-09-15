Fix and complete the PostgreSQL 16 analytics pipeline in `/app/analytics.sql`. The file defines a `margin_category` PL/pgSQL function and six views against a `sales` table (24 rows; schema and data in `/app/setup.sql`). Several objects contain bugs producing incorrect results, and one view is a stub requiring implementation from scratch. Views `v_sales_enriched` and `v_ranked_tiers` depend on upstream objects — cascading bugs must be resolved through the dependency chain.

**Database**: `analytics_db`, user `postgres`, trust authentication. Start PostgreSQL with `pg_ctlcluster 16 main start`. All channel values are lowercase (`'online'`, `'retail'`). All data columns are non-NULL.

**Function `margin_category(p_cost, p_revenue)`**: Returns a tier based on profit margin percentage `(revenue − cost) / revenue × 100`: `'low'` for \[0, 20), `'standard'` for \[20, 40), `'high'` for \[40, 60), `'premium'` for \[60, 100\]. Returns `'undefined'` when revenue is zero.

**View `v_sales_enriched`**: Every sales row plus: `margin_tier` (from the function with `cost` as first arg, `amount` as second), `running_total` (cumulative `SUM(amount)` partitioned by region, ordered by `sale_date`, row-based frame ending at the current row), `amount_rank` (`RANK` by amount descending within region).

**View `v_cube_analysis`**: `CUBE(region, category)` producing 16 rows. Columns: `region, category, total_revenue, total_cost, num_txns, g_region, g_category, level_label`. Label mapping via `GROUPING(region, category)`: 0→`'detail'`, 1→`'by_region'`, 2→`'by_category'`, 3→`'grand_total'`.

**View `v_channel_metrics`**: `ROLLUP(region)` producing 4 rows. Includes `online_revenue` (case-sensitive `'online'` filter), `retail_revenue`, `num_categories` (distinct category count), `high_qty_revenue` (strict `quantity > 5` filter), and `profit_margin_pct` = `ROUND(SUM(amount - cost) * 100.0 / SUM(amount), 2)`.

**View `v_threshold_regions`**: `ROLLUP(region)` filtered by `HAVING SUM(amount) > threshold`, where the threshold equals total revenue divided by the number of distinct regions. Column `pct_of_total` = group revenue / grand total revenue × 100, rounded to 2 decimals.

**View `v_quarterly_growth`** (stub — implement from scratch): Uses `GROUPING SETS` over `(quarter_num, region)`, `(quarter_num)`, and `()` to produce 8 rows. Columns: `quarter_num` (integer 1–4 extracted from `sale_date`), `region`, `total_revenue`, `total_cost`, `profit_margin_pct`, `g_region`, `g_quarter`, `growth_rate_pct`. Growth rate is the quarter-over-quarter percentage change in revenue via `LAG`, partitioned by aggregation level and region. Order: `g_quarter, g_region, quarter_num NULLS LAST, region NULLS LAST`.

**View `v_ranked_tiers`**: Reads from `v_sales_enriched`. Uses `DENSE_RANK` partitioned by `margin_tier`, ordered by `amount DESC`. Returns only rows with `tier_rank <= 3`. Columns: `region, category, amount, margin_tier, tier_rank`. Order: `margin_tier, tier_rank, region`.

**Deliverable**: A corrected `/app/analytics.sql` that creates all objects and produces correct query results.

Verification: `/tests/test.sh`
