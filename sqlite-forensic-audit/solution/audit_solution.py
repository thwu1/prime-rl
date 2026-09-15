#!/usr/bin/env python3
"""Forensic audit of warehouse.db — computes all required metrics and evaluates original report."""

import sqlite3
import json


def main():
    conn = sqlite3.connect('/app/warehouse.db')
    c = conn.cursor()
    results = {}

    # 1. phantom_duplicate_groups
    c.execute("""
        SELECT COUNT(*) FROM (
            SELECT product_id, warehouse_id
            FROM inventory
            WHERE lot_number IS NULL
            GROUP BY product_id, warehouse_id
            HAVING COUNT(*) >= 2
        )
    """)
    results['phantom_duplicate_groups'] = c.fetchone()[0]

    # 2. inventory_text_quantities
    c.execute("SELECT COUNT(*) FROM inventory WHERE typeof(quantity) = 'text'")
    results['inventory_text_quantities'] = c.fetchone()[0]

    # 3. product_text_prices
    c.execute("SELECT COUNT(*) FROM products WHERE typeof(unit_price) = 'text'")
    results['product_text_prices'] = c.fetchone()[0]

    # 4. orphaned_product_categories
    c.execute("""
        SELECT COUNT(*) FROM products
        WHERE category_id NOT IN (SELECT id FROM categories)
    """)
    results['orphaned_product_categories'] = c.fetchone()[0]

    # 5. orphaned_transactions
    c.execute("""
        SELECT COUNT(*) FROM transactions
        WHERE inventory_id NOT IN (SELECT id FROM inventory)
    """)
    results['orphaned_transactions'] = c.fetchone()[0]

    # 6. max_category_depth (root = depth 1)
    c.execute("""
        WITH RECURSIVE cat_tree AS (
            SELECT id, 1 AS depth
            FROM categories
            WHERE parent_id IS NULL
            UNION ALL
            SELECT c.id, ct.depth + 1
            FROM categories c
            JOIN cat_tree ct ON c.parent_id = ct.id
        )
        SELECT MAX(depth) FROM cat_tree
    """)
    results['max_category_depth'] = c.fetchone()[0]

    # 7. json_price_discrepancies
    c.execute("""
        SELECT COUNT(*) FROM products
        WHERE metadata IS NOT NULL
          AND ABS(
                json_extract(metadata, '$.list_price')
                - CAST(unit_price AS REAL)
              ) > 0.01
    """)
    results['json_price_discrepancies'] = c.fetchone()[0]

    # 8. stat1_anomalies
    c.execute("SELECT tbl, idx, stat FROM sqlite_stat1 WHERE idx IS NOT NULL")
    stat_entries = c.fetchall()

    c.execute("SELECT name FROM sqlite_master WHERE type='index'")
    real_indexes = {row[0] for row in c.fetchall()}

    anomalies = 0
    for tbl, idx, stat in stat_entries:
        if idx not in real_indexes:
            anomalies += 1
            continue
        reported_count = int(stat.split()[0])
        c.execute(f"SELECT COUNT(*) FROM [{tbl}]")
        actual_count = c.fetchone()[0]
        if actual_count > 0:
            if abs(reported_count - actual_count) / actual_count > 0.2:
                anomalies += 1
        elif reported_count > 0:
            anomalies += 1
    results['stat1_anomalies'] = anomalies

    # 9. total_inventory_value
    c.execute("""
        SELECT ROUND(SUM(i.quantity * p.unit_price), 2)
        FROM inventory i
        JOIN products p ON i.product_id = p.id
        WHERE typeof(i.quantity) = 'integer'
          AND typeof(p.unit_price) IN ('integer', 'real')
    """)
    results['total_inventory_value'] = c.fetchone()[0]

    # 10. inventory_value_by_root_category
    c.execute("""
        WITH RECURSIVE cat_tree AS (
            SELECT id, id AS root_id, name AS root_name
            FROM categories
            WHERE parent_id IS NULL
            UNION ALL
            SELECT c.id, ct.root_id, ct.root_name
            FROM categories c
            JOIN cat_tree ct ON c.parent_id = ct.id
        )
        SELECT ct.root_name,
               ROUND(SUM(i.quantity * p.unit_price), 2) AS total_value
        FROM cat_tree ct
        JOIN products p ON p.category_id = ct.id
        JOIN inventory i ON i.product_id = p.id
        WHERE typeof(i.quantity) = 'integer'
          AND typeof(p.unit_price) IN ('integer', 'real')
        GROUP BY ct.root_id, ct.root_name
    """)
    results['inventory_value_by_root_category'] = {
        row[0]: row[1] for row in c.fetchall()
    }

    conn.close()

    # Write corrected report
    with open('/app/corrected_report.json', 'w') as f:
        json.dump(results, f, indent=2)

    # Evaluate original report: determine which values were already correct
    with open('/app/report_output.json', 'r') as f:
        original = json.load(f)

    correct_keys = []
    for key in results:
        orig_val = original.get(key)
        corr_val = results[key]
        if orig_val is None:
            continue
        if isinstance(corr_val, int):
            if orig_val == corr_val:
                correct_keys.append(key)
        elif isinstance(corr_val, float):
            if isinstance(orig_val, (int, float)) and abs(orig_val - corr_val) <= 0.01:
                correct_keys.append(key)
        elif isinstance(corr_val, dict):
            if isinstance(orig_val, dict) and set(orig_val.keys()) == set(corr_val.keys()):
                all_match = True
                for k in corr_val:
                    if k not in orig_val or not isinstance(orig_val[k], (int, float)):
                        all_match = False
                        break
                    if abs(orig_val[k] - corr_val[k]) > 0.01:
                        all_match = False
                        break
                if all_match:
                    correct_keys.append(key)

    correct_keys.sort()
    with open('/app/error_analysis.json', 'w') as f:
        json.dump({"correct_keys": correct_keys}, f, indent=2)


if __name__ == '__main__':
    main()
