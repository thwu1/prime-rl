#!/usr/bin/env python3
"""Analyze /app/analytics.db, diagnose all issues, and generate repair.sql."""

import sqlite3

DB_PATH = '/app/analytics.db'
OUTPUT = '/app/repair.sql'

conn = sqlite3.connect(DB_PATH)
conn.execute("PRAGMA foreign_keys = OFF")
cur = conn.cursor()

sql_lines = []
sql_lines.append("-- Auto-generated repair script")
sql_lines.append("-- Idempotent: safe to run multiple times")
sql_lines.append("")

# ==================================================================
# FIX 1: Break self-references and remaining cycles in categories
# ==================================================================

sql_lines.append("-- FIX 1: Repair category hierarchy")
sql_lines.append("-- Fix self-referencing nodes")
sql_lines.append(
    "UPDATE categories SET parent_id = NULL WHERE id = parent_id;")

# Simulate fixes to check for remaining unreachable nodes
cats = {r[0]: r[1] for r in
        cur.execute("SELECT id, parent_id FROM categories").fetchall()}

# Apply self-ref fix in simulation
for cid in list(cats.keys()):
    if cats[cid] == cid:
        cats[cid] = None

# Find reachable via BFS from roots
roots = {cid for cid, pid in cats.items() if pid is None}
reachable = set(roots)
changed = True
while changed:
    changed = False
    for cid, pid in cats.items():
        if cid not in reachable and pid in reachable:
            reachable.add(cid)
            changed = True

# Break any remaining cycles
unreachable = sorted(set(cats.keys()) - reachable)
if unreachable:
    visited = set()
    for start in unreachable:
        if start in visited:
            continue
        cycle = set()
        node = start
        while node is not None and node not in cycle and node not in visited:
            cycle.add(node)
            node = cats.get(node)
        visited.update(cycle)
        promote = min(cycle)
        sql_lines.append(
            f"UPDATE categories SET parent_id = NULL "
            f"WHERE id = {promote} AND parent_id IS NOT NULL;")

sql_lines.append("")

# ==================================================================
# FIX 2: Rewrite monthly_revenue view
# ==================================================================

sql_lines.append("-- FIX 2: Fix monthly_revenue view")
sql_lines.append("DROP VIEW IF EXISTS monthly_revenue;")
sql_lines.append("""CREATE VIEW monthly_revenue AS
SELECT
    strftime('%Y-%m', o.order_date) AS month,
    p.id AS product_id,
    p.name AS product_name,
    SUM(oi.quantity * oi.unit_price) AS total_revenue,
    COUNT(oi.id) AS item_count
FROM order_items oi
JOIN orders o ON oi.order_id = o.id
JOIN products p ON oi.product_id = p.id
GROUP BY month, p.id;""")
sql_lines.append("")

# ==================================================================
# FIX 3: Rewrite product_best_review view
# ==================================================================

sql_lines.append("-- FIX 3: Fix product_best_review view")
sql_lines.append("DROP VIEW IF EXISTS product_best_review;")
sql_lines.append("""CREATE VIEW product_best_review AS
SELECT
    product_id,
    best_rating,
    best_comment,
    reviewer_id,
    review_date
FROM (
    SELECT
        product_id,
        rating        AS best_rating,
        comment       AS best_comment,
        user_id       AS reviewer_id,
        created_at    AS review_date,
        ROW_NUMBER() OVER (
            PARTITION BY product_id
            ORDER BY rating DESC, created_at DESC
        ) AS rn
    FROM reviews
)
WHERE rn = 1;""")
sql_lines.append("")

# ==================================================================
# FIX 4: Insert placeholder users for orphaned orders
# ==================================================================

sql_lines.append("-- FIX 4: Insert placeholder users for orphaned orders")

cur.execute('''
    SELECT DISTINCT o.user_id
    FROM orders o
    LEFT JOIN users u ON o.user_id = u.id
    WHERE u.id IS NULL
    ORDER BY o.user_id
''')
orphan_uids = [r[0] for r in cur.fetchall()]

for uid in orphan_uids:
    sql_lines.append(
        f"INSERT OR IGNORE INTO users "
        f"(id, username, email, tier, region, created_at) "
        f"VALUES ({uid}, '[deleted_user_{uid}]', "
        f"'deleted_{uid}@placeholder.invalid', 'N/A', 'N/A', "
        f"'1970-01-01 00:00:00');")

sql_lines.append("")

# ==================================================================
# FIX 5: Insert placeholder products for orphaned order_items
# ==================================================================

sql_lines.append(
    "-- FIX 5: Insert placeholder products for orphaned order_items")

# Use a valid root category for placeholder products
root_cat = cur.execute(
    "SELECT id FROM categories WHERE parent_id IS NULL ORDER BY id LIMIT 1"
).fetchone()
root_cat_id = root_cat[0] if root_cat else 1

cur.execute('''
    SELECT DISTINCT oi.product_id
    FROM order_items oi
    LEFT JOIN products p ON oi.product_id = p.id
    WHERE p.id IS NULL
    ORDER BY oi.product_id
''')
orphan_pids = [r[0] for r in cur.fetchall()]

for pid in orphan_pids:
    sql_lines.append(
        f"INSERT OR IGNORE INTO products "
        f"(id, name, category_id, price, status, created_at) "
        f"VALUES ({pid}, '[deleted_product_{pid}]', {root_cat_id}, "
        f"0.0, 'discontinued', '1970-01-01 00:00:00');")

sql_lines.append("")

# ==================================================================
# FIX 6: Fix products with invalid category_ids (DBA damage)
# ==================================================================

sql_lines.append(
    "-- FIX 6: Fix products with invalid category_ids")
sql_lines.append(
    f"UPDATE products SET category_id = {root_cat_id} "
    f"WHERE category_id NOT IN (SELECT id FROM categories);")
sql_lines.append("")

# ==================================================================
# FIX 7: Normalize event dates to ISO-8601
# ==================================================================

sql_lines.append("-- FIX 7: Normalize event dates to ISO-8601")

# Epoch milliseconds (13-digit all-numeric)
sql_lines.append("""UPDATE events
SET occurred_at = datetime(CAST(occurred_at AS INTEGER) / 1000, 'unixepoch')
WHERE length(occurred_at) = 13
  AND occurred_at GLOB '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'
  AND occurred_at NOT LIKE '____-__-__ __:__:__';""")

# Unix timestamps (10-digit all-numeric)
sql_lines.append("""UPDATE events
SET occurred_at = datetime(CAST(occurred_at AS INTEGER), 'unixepoch')
WHERE length(occurred_at) = 10
  AND occurred_at GLOB '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'
  AND occurred_at NOT LIKE '____-__-__ __:__:__';""")

# US format: MM/DD/YYYY HH:MM:SS -> YYYY-MM-DD HH:MM:SS
sql_lines.append("""UPDATE events
SET occurred_at =
    substr(occurred_at, 7, 4) || '-' ||
    substr(occurred_at, 1, 2) || '-' ||
    substr(occurred_at, 4, 2) || ' ' ||
    substr(occurred_at, 12)
WHERE occurred_at LIKE '__/__/____ __:__:__';""")

sql_lines.append("")

# ==================================================================
# FIX 8: Regenerate sqlite_stat1
# ==================================================================

sql_lines.append(
    "-- FIX 8: Regenerate query planner statistics")
sql_lines.append("ANALYZE;")
sql_lines.append("")

conn.close()

# Write the repair script
with open(OUTPUT, 'w') as f:
    f.write('\n'.join(sql_lines) + '\n')

print(f"Wrote {OUTPUT} ({len(sql_lines)} lines)")
print(f"  Orphaned user IDs: {orphan_uids}")
print(f"  Orphaned product IDs: {orphan_pids}")
