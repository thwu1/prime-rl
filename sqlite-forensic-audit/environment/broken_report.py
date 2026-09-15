#!/usr/bin/env python3
"""Warehouse financial report generator."""
import sqlite3
import json

conn = sqlite3.connect('/app/warehouse.db')
c = conn.cursor()
report = {}

# Duplicate inventory entries - counts individual NULL lot rows, not groups
c.execute("SELECT COUNT(*) FROM inventory WHERE lot_number IS NULL")
report['phantom_duplicate_groups'] = c.fetchone()[0]

# Non-numeric quantities - only catches obviously non-numeric text
c.execute("""
    SELECT COUNT(*) FROM inventory
    WHERE quantity GLOB '*[^0-9.]*' AND quantity IS NOT NULL
""")
report['inventory_text_quantities'] = c.fetchone()[0]

# Non-numeric prices
c.execute("""
    SELECT COUNT(*) FROM products
    WHERE unit_price GLOB '*[^0-9.]*' AND unit_price IS NOT NULL
""")
report['product_text_prices'] = c.fetchone()[0]

# Orphaned product categories
c.execute("""
    SELECT COUNT(*) FROM products
    WHERE category_id NOT IN (SELECT id FROM categories)
""")
report['orphaned_product_categories'] = c.fetchone()[0]

# Orphaned transactions
c.execute("""
    SELECT COUNT(*) FROM transactions
    WHERE inventory_id NOT IN (SELECT id FROM inventory)
""")
report['orphaned_transactions'] = c.fetchone()[0]

# Category depth - incorrect: counts distinct parent_id values
c.execute("""
    SELECT COUNT(DISTINCT parent_id) + 1 FROM categories
    WHERE parent_id IS NOT NULL
""")
report['max_category_depth'] = c.fetchone()[0]

# JSON price discrepancies
c.execute("""
    SELECT COUNT(*) FROM products
    WHERE metadata IS NOT NULL
      AND ABS(json_extract(metadata, '$.list_price') - unit_price) > 0.01
""")
report['json_price_discrepancies'] = c.fetchone()[0]

# Query planner anomalies - just counts all stat1 entries
c.execute("SELECT COUNT(*) FROM sqlite_stat1")
report['stat1_anomalies'] = c.fetchone()[0]

# Total inventory value - no type filtering
c.execute("""
    SELECT ROUND(SUM(i.quantity * p.unit_price), 2)
    FROM inventory i
    JOIN products p ON i.product_id = p.id
""")
report['total_inventory_value'] = c.fetchone()[0]

# Value by root category - only includes products directly in root categories
c.execute("""
    SELECT cat.name, ROUND(SUM(i.quantity * p.unit_price), 2)
    FROM inventory i
    JOIN products p ON i.product_id = p.id
    JOIN categories cat ON p.category_id = cat.id
    WHERE cat.parent_id IS NULL
    GROUP BY cat.name
""")
report['inventory_value_by_root_category'] = {
    row[0]: row[1] for row in c.fetchall()
}

conn.close()

with open('/app/report_output.json', 'w') as f:
    json.dump(report, f, indent=2)

print("Report generated at /app/report_output.json")
