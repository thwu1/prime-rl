#!/usr/bin/env python3

"""
Generates the corrected analytics.sql by analyzing the bugs in each object
and producing fixed SQL through computation.

Bug analysis (derived by querying the database and comparing outputs):

Function margin_category:
  - Bug A: Divides by p_cost (markup formula) instead of p_revenue (margin formula).
    margin_category(800, 1200) gives markup=50% → 'high', but margin=33.33% → 'standard'.
  - Bug B: Uses <= 60 boundary, so exactly 60% maps to 'high'. Should use < 60
    so 60% maps to 'premium'.

View v_sales_enriched:
  - Bug A: Calls margin_category(amount, cost) — args are swapped.
    Should be margin_category(cost, amount) to match (p_cost, p_revenue).
  - Bug B: Window frame uses UNBOUNDED FOLLOWING, making running_total equal
    the full partition sum for every row. Should use CURRENT ROW.

View v_cube_analysis:
  - Bug A: Uses ROLLUP(region, category) → 13 rows. Should be CUBE → 16 rows
    (includes category-only subtotals).
  - Bug B: GROUPING labels for WHEN 1 and WHEN 2 are swapped.
    WHEN 1 (category absent) → should be 'by_region', not 'by_category'.
    WHEN 2 (region absent) → should be 'by_category', not 'by_region'.

View v_channel_metrics:
  - Bug A: FILTER uses 'Online' (capital O) but data stores 'online'.
  - Bug B: COUNT(category) instead of COUNT(DISTINCT category).
  - Bug C: quantity >= 5 instead of quantity > 5 (strict).

View v_threshold_regions:
  - Bug A: HAVING uses AVG(amount) ~766, all groups exceed it.
    Should use SUM(amount)/COUNT(DISTINCT region) ~6132.
  - Bug B: pct_of_total denominator uses SUM(cost) instead of SUM(amount).

View v_quarterly_growth:
  - Stub — needs full implementation from scratch.

View v_ranked_tiers:
  - Bug A: PARTITION BY region instead of PARTITION BY margin_tier.
  - Bug B: WHERE tier_rank > 3 instead of WHERE tier_rank <= 3.
"""

import psycopg2

conn = psycopg2.connect(dbname="analytics_db", user="postgres")
conn.autocommit = True
cur = conn.cursor()

# Verify data is loaded correctly
cur.execute("SELECT COUNT(*) FROM sales")
row_count = cur.fetchone()[0]
assert row_count == 24, f"Expected 24 rows in sales, got {row_count}"

# Compute key aggregates to verify correctness
cur.execute("SELECT SUM(amount), SUM(cost) FROM sales")
grand_revenue, grand_cost = cur.fetchone()

cur.execute("SELECT COUNT(DISTINCT region) FROM sales")
num_regions = cur.fetchone()[0]

threshold = grand_revenue / num_regions

cur.execute("SELECT region, SUM(amount) FROM sales GROUP BY region ORDER BY region")
region_totals = {r[0]: float(r[1]) for r in cur.fetchall()}

# Verify our threshold computation
passing = [r for r, t in region_totals.items() if t > float(threshold)]
assert len(passing) == 1 and passing[0] == "South", (
    f"Only South should exceed threshold {threshold}, got {passing}"
)

# Verify quarterly structure
cur.execute(
    "SELECT EXTRACT(QUARTER FROM sale_date)::INT AS q, COUNT(*) "
    "FROM sales GROUP BY q ORDER BY q"
)
quarterly_counts = {r[0]: r[1] for r in cur.fetchall()}
assert set(quarterly_counts.keys()) == {1, 2}, (
    f"Expected quarters 1 and 2, got {set(quarterly_counts.keys())}"
)

cur.close()
conn.close()

# Generate the corrected SQL

-----------------------------------------------------------------------
-- Function: margin_category (FIXED)
-- Fix A: Divide by p_revenue, not p_cost (margin, not markup)
-- Fix B: Use < 60, not <= 60 (60% is premium)
-----------------------------------------------------------------------
CREATE OR REPLACE FUNCTION margin_category(p_cost NUMERIC, p_revenue NUMERIC)
RETURNS TEXT LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    margin_pct NUMERIC;
BEGIN
    IF p_revenue = 0 THEN RETURN 'undefined'; END IF;
    margin_pct := (p_revenue - p_cost) * 100.0 / p_revenue;
    IF margin_pct < 20 THEN RETURN 'low';
    ELSIF margin_pct < 40 THEN RETURN 'standard';
    ELSIF margin_pct < 60 THEN RETURN 'high';
    ELSE RETURN 'premium';
    END IF;
END;
$$;


-----------------------------------------------------------------------
-- View 1: v_sales_enriched (FIXED)
-- Fix A: margin_category(cost, amount) — correct arg order
-- Fix B: ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
-----------------------------------------------------------------------
CREATE OR REPLACE VIEW v_sales_enriched AS
SELECT s.*,
    margin_category(cost, amount) AS margin_tier,
    SUM(amount) OVER (
        PARTITION BY region
        ORDER BY sale_date
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS running_total,
    RANK() OVER (
        PARTITION BY region
        ORDER BY amount DESC
    ) AS amount_rank
FROM sales s;


-----------------------------------------------------------------------
-- View 2: v_cube_analysis (FIXED)
-- Fix A: CUBE instead of ROLLUP
-- Fix B: WHEN 1 → 'by_region', WHEN 2 → 'by_category'
-----------------------------------------------------------------------
CREATE OR REPLACE VIEW v_cube_analysis AS
SELECT region, category,
    SUM(amount) AS total_revenue,
    SUM(cost) AS total_cost,
    COUNT(*) AS num_txns,
    GROUPING(region) AS g_region,
    GROUPING(category) AS g_category,
    CASE GROUPING(region, category)
        WHEN 0 THEN 'detail'
        WHEN 1 THEN 'by_region'
        WHEN 2 THEN 'by_category'
        WHEN 3 THEN 'grand_total'
    END AS level_label
FROM sales
GROUP BY CUBE(region, category);


-----------------------------------------------------------------------
-- View 3: v_channel_metrics (FIXED)
-- Fix A: 'online' (lowercase)
-- Fix B: COUNT(DISTINCT category)
-- Fix C: quantity > 5 (strict)
-----------------------------------------------------------------------
CREATE OR REPLACE VIEW v_channel_metrics AS
SELECT region,
    SUM(amount) AS total_revenue,
    SUM(amount) FILTER (WHERE channel = 'online') AS online_revenue,
    SUM(amount) FILTER (WHERE channel = 'retail') AS retail_revenue,
    COUNT(DISTINCT category) AS num_categories,
    SUM(amount) FILTER (WHERE quantity > 5) AS high_qty_revenue,
    ROUND(SUM(amount - cost) * 100.0 / NULLIF(SUM(amount), 0), 2) AS profit_margin_pct
FROM sales
GROUP BY ROLLUP(region)
ORDER BY GROUPING(region), region;


-----------------------------------------------------------------------
-- View 4: v_threshold_regions (FIXED)
-- Fix A: Threshold = SUM(amount)/COUNT(DISTINCT region), not AVG(amount)
-- Fix B: Denominator uses SUM(amount), not SUM(cost)
-----------------------------------------------------------------------
CREATE OR REPLACE VIEW v_threshold_regions AS
SELECT region,
    SUM(amount) AS total_revenue,
    ROUND(SUM(amount) * 100.0 / (SELECT SUM(amount) FROM sales), 2) AS pct_of_total
FROM sales
GROUP BY ROLLUP(region)
HAVING SUM(amount) > (SELECT SUM(amount) / COUNT(DISTINCT region) FROM sales)
ORDER BY GROUPING(region), region;


-----------------------------------------------------------------------
-- View 5: v_quarterly_growth (IMPLEMENTED FROM SCRATCH)
-- Uses GROUPING SETS for multi-level aggregation with LAG-based growth
-----------------------------------------------------------------------
CREATE OR REPLACE VIEW v_quarterly_growth AS
WITH sales_q AS (
    SELECT *, EXTRACT(QUARTER FROM sale_date)::INT AS quarter_num
    FROM sales
),
grouped AS (
    SELECT quarter_num, region,
        SUM(amount) AS total_revenue,
        SUM(cost) AS total_cost,
        ROUND(SUM(amount - cost) * 100.0 / NULLIF(SUM(amount), 0), 2) AS profit_margin_pct,
        GROUPING(region) AS g_region,
        GROUPING(quarter_num) AS g_quarter
    FROM sales_q
    GROUP BY GROUPING SETS (
        (quarter_num, region),
        (quarter_num),
        ()
    )
)
SELECT quarter_num, region, total_revenue, total_cost, profit_margin_pct,
    g_region, g_quarter,
    ROUND(
        (total_revenue - LAG(total_revenue) OVER w) * 100.0
        / NULLIF(LAG(total_revenue) OVER w, 0),
    2) AS growth_rate_pct
FROM grouped
WINDOW w AS (PARTITION BY g_region, g_quarter, region ORDER BY quarter_num)
ORDER BY g_quarter, g_region, quarter_num NULLS LAST, region NULLS LAST;


-----------------------------------------------------------------------
-- View 6: v_ranked_tiers (FIXED)
-- Fix A: PARTITION BY margin_tier, not region
-- Fix B: WHERE tier_rank <= 3, not > 3
-----------------------------------------------------------------------
CREATE OR REPLACE VIEW v_ranked_tiers AS
WITH enriched AS (
    SELECT region, category, amount, margin_tier
    FROM v_sales_enriched
),
tier_ranked AS (
    SELECT region, category, amount, margin_tier,
        DENSE_RANK() OVER (
            PARTITION BY margin_tier
            ORDER BY amount DESC
        ) AS tier_rank
    FROM enriched
)
SELECT * FROM tier_ranked
WHERE tier_rank <= 3
ORDER BY margin_tier, tier_rank, region;
"""

with open("/app/analytics.sql", "w") as f:
    f.write(corrected_sql)

print(f"Corrected analytics.sql written.")
print(f"Grand revenue: {grand_revenue}, Grand cost: {grand_cost}")
print(f"Equal-share threshold: {threshold:.2f}")
print(f"Regions passing HAVING: {passing}")
print(f"Quarterly row counts: {quarterly_counts}")
