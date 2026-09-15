#!/usr/bin/env python3
"""
Solution for PostgreSQL Performance Optimization Challenge.

Investigates the database state, captures before-costs, writes a diagnosis,
creates and applies a remediation SQL script, captures after-costs, and
produces an evaluation comparing before/after performance.
"""

import json
import re
import subprocess
import sys


def psql(query, db="benchdb"):
    """Run a psql query and return stdout."""
    result = subprocess.run(
        ["psql", "-U", "postgres", "-d", db, "-t", "-A", "-c", query],
        capture_output=True, text=True, timeout=120
    )
    return result.stdout.strip()


def psql_file(filepath, db="benchdb"):
    """Run a SQL file via psql."""
    result = subprocess.run(
        ["psql", "-U", "postgres", "-d", db, "-f", filepath],
        capture_output=True, text=True, timeout=300
    )
    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return result.returncode


def get_explain_cost(query):
    """Get the total estimated cost from EXPLAIN for a query."""
    explain = psql(f"EXPLAIN {query}")
    # Parse cost=X.XX..Y.YY from the first line — Y.YY is total cost
    match = re.search(r'cost=[\d.]+\.\.([\d.]+)', explain)
    if match:
        return float(match.group(1))
    return 0.0


def read_query(path):
    """Read a SQL query from a file, stripping comments."""
    with open(path) as f:
        lines = f.readlines()
    # Strip SQL comment lines
    return " ".join(l.strip() for l in lines if not l.strip().startswith("--"))


# ==================== STEP 1: CAPTURE BEFORE-COSTS ====================

print("=" * 60)
print("STEP 1: CAPTURING BEFORE-COSTS")
print("=" * 60)

queries = {}
before_costs = {}
for qid in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
    qpath = f"/app/queries/{qid}.sql"
    queries[qid] = read_query(qpath)
    before_costs[qid] = get_explain_cost(queries[qid])
    print(f"{qid} before cost: {before_costs[qid]}")


# ==================== STEP 2: INVESTIGATE ====================

print("\n" + "=" * 60)
print("STEP 2: INVESTIGATING DATABASE STATE")
print("=" * 60)

# Check existing indexes
print("\n--- Existing indexes ---")
indexes = psql(
    "SELECT tablename, indexname FROM pg_indexes "
    "WHERE schemaname = 'public' ORDER BY tablename, indexname;"
)
print(indexes)

# Check table statistics (bloat)
print("\n--- Table statistics (bloat check) ---")
stats = psql(
    "SELECT relname, n_live_tup, n_dead_tup, "
    "CASE WHEN n_live_tup + n_dead_tup > 0 "
    "THEN round(100.0 * n_dead_tup / (n_live_tup + n_dead_tup), 1) "
    "ELSE 0 END AS dead_pct "
    "FROM pg_stat_user_tables ORDER BY n_dead_tup DESC;"
)
print(stats)

# Check work_mem
print("\n--- Configuration ---")
work_mem = psql("SHOW work_mem;")
print(f"work_mem = {work_mem}")

# Check EXPLAIN for view query
print("\n--- EXPLAIN for product_summary view (Q4) ---")
explain_q4 = psql("EXPLAIN SELECT * FROM product_summary WHERE category = 'Electronics' LIMIT 20;")
print(explain_q4)


# ==================== STEP 3: DIAGNOSIS ====================

print("\n" + "=" * 60)
print("STEP 3: WRITING DIAGNOSIS")
print("=" * 60)

diagnosis = {
    "Q1": "MISSING_INDEX",
    "Q2": "TABLE_BLOAT",
    "Q3": "LOW_WORK_MEM",
    "Q4": "CORRELATED_SUBQUERY",
    "Q5": "MISSING_INDEX"
}

with open("/app/diagnosis.json", "w") as f:
    json.dump(diagnosis, f, indent=2)
print("Wrote /app/diagnosis.json")
print(json.dumps(diagnosis, indent=2))


# ==================== STEP 4: CREATE AND APPLY FIX ====================

print("\n" + "=" * 60)
print("STEP 4: CREATING AND APPLYING FIX SCRIPT")
print("=" * 60)

fix_sql = """\
-- PostgreSQL Performance Remediation Script

-- Index for Q1: composite index for customer+date range queries
CREATE INDEX IF NOT EXISTS idx_orders_cust_date
    ON orders(customer_id, order_date);

-- Index for Q5: join index on order_items
CREATE INDEX IF NOT EXISTS idx_oi_order_id
    ON order_items(order_id);

-- Additional useful indexes
CREATE INDEX IF NOT EXISTS idx_oi_product_id
    ON order_items(product_id);
CREATE INDEX IF NOT EXISTS idx_reviews_product_id
    ON reviews(product_id);
CREATE INDEX IF NOT EXISTS idx_reviews_customer_id
    ON reviews(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_status
    ON orders(status);

-- Resolve table bloat on orders
VACUUM FULL orders;

-- Set adequate work_mem and tune related settings
ALTER SYSTEM SET work_mem = '64MB';
ALTER SYSTEM SET effective_cache_size = '1GB';
ALTER SYSTEM SET random_page_cost = 1.1;
ALTER SYSTEM SET autovacuum = on;
SELECT pg_reload_conf();

-- Rewrite product_summary view using pre-aggregated derived tables
-- to eliminate correlated subqueries and avoid cross-join inflation
CREATE OR REPLACE VIEW product_summary AS
SELECT
    p.id,
    p.name,
    p.category,
    p.price,
    r_agg.avg_rating,
    COALESCE(r_agg.review_count, 0) AS review_count,
    COALESCE(oi_agg.total_sold, 0) AS total_sold
FROM products p
LEFT JOIN (
    SELECT product_id,
           AVG(rating) AS avg_rating,
           COUNT(*) AS review_count
    FROM reviews
    GROUP BY product_id
) r_agg ON r_agg.product_id = p.id
LEFT JOIN (
    SELECT product_id,
           SUM(quantity) AS total_sold
    FROM order_items
    GROUP BY product_id
) oi_agg ON oi_agg.product_id = p.id;

-- Update statistics
ANALYZE;
"""

with open("/app/fix.sql", "w") as f:
    f.write(fix_sql)
print("Wrote /app/fix.sql")

rc = psql_file("/app/fix.sql")
if rc == 0:
    print("\nFixes applied successfully.")
else:
    print(f"\nFix script exited with code {rc}", file=sys.stderr)


# ==================== STEP 5: CAPTURE AFTER-COSTS & EVALUATION ====================

print("\n" + "=" * 60)
print("STEP 5: CAPTURING AFTER-COSTS AND WRITING EVALUATION")
print("=" * 60)

evaluation = {}
for qid in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
    after_cost = get_explain_cost(queries[qid])
    bc = before_costs[qid]
    ac = after_cost
    factor = round(bc / ac, 1) if ac > 0 else 999.9
    evaluation[qid] = {
        "before_cost": bc,
        "after_cost": ac,
        "improvement_factor": factor
    }
    print(f"{qid}: before={bc}, after={ac}, improvement={factor}x")

with open("/app/evaluation.json", "w") as f:
    json.dump(evaluation, f, indent=2)
print("\nWrote /app/evaluation.json")


# ==================== STEP 6: VERIFY ====================

print("\n" + "=" * 60)
print("STEP 6: VERIFICATION")
print("=" * 60)

print("\n--- Dead tuple check ---")
bloat = psql(
    "SELECT relname, n_dead_tup, n_live_tup "
    "FROM pg_stat_user_tables WHERE relname = 'orders';"
)
print(f"orders: {bloat}")

print("\n--- work_mem check ---")
wm = psql("SHOW work_mem;")
print(f"work_mem = {wm}")

print("\n--- View EXPLAIN check ---")
explain_after = psql(
    "EXPLAIN SELECT * FROM product_summary "
    "WHERE category = 'Electronics' LIMIT 20;"
)
has_subplan = "SubPlan" in explain_after
print(f"SubPlan in EXPLAIN: {has_subplan}")

print("\n--- View correctness check ---")
view_reviews = psql(
    "SELECT COALESCE(SUM(review_count),0)::bigint FROM product_summary;"
)
actual_reviews = psql("SELECT COUNT(*)::bigint FROM reviews;")
print(f"View review total: {view_reviews}, Actual: {actual_reviews}, "
      f"Match: {view_reviews == actual_reviews}")

view_sold = psql(
    "SELECT COALESCE(SUM(total_sold),0)::bigint FROM product_summary;"
)
actual_sold = psql("SELECT COALESCE(SUM(quantity),0)::bigint FROM order_items;")
print(f"View sold total: {view_sold}, Actual: {actual_sold}, "
      f"Match: {view_sold == actual_sold}")

print("\nDone.")
