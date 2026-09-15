#!/usr/bin/env python3
"""
Fix all six bugs in the SQLMesh analytics pipeline.

Bug 1: config.yaml has wrong dialect (postgres instead of duckdb)
Bug 2: stg_orders.sql time_column doesn't match output column name
Bug 3: daily_revenue.sql missing required WHERE clause for INCREMENTAL_BY_TIME_RANGE
Bug 4: top_products.sql references non-existent upstream model
Bug 5: revenue_checks.sql audit logic is inverted (returns good rows instead of bad)
Bug 6: test_daily_revenue.yaml expected output uses wrong column names
"""


import os


def fix_file(path, replacements):
    """Apply a list of (old, new) string replacements to a file."""
    with open(path) as f:
        content = f.read()
    for old, new in replacements:
        if old not in content:
            print(f"  WARNING: pattern not found in {path}: {old!r}")
            continue
        content = content.replace(old, new)
    with open(path, 'w') as f:
        f.write(content)
    print(f"  Fixed: {path}")


def main():
    print("Applying fixes to SQLMesh pipeline...\n")

    # Fix 1: Config dialect — postgres -> duckdb
    print("[1/6] Fixing config.yaml dialect")
    fix_file('/app/config.yaml', [
        ('dialect: postgres', 'dialect: duckdb'),
    ])

    # Fix 2: stg_orders time_column — ordered_at -> order_timestamp
    print("[2/6] Fixing stg_orders.sql time_column")
    fix_file('/app/models/staging/stg_orders.sql', [
        ('time_column ordered_at', 'time_column order_timestamp'),
    ])

    # Fix 3: daily_revenue missing WHERE clause — add time range filter
    print("[3/6] Adding WHERE clause to daily_revenue.sql")
    fix_file('/app/models/analytics/daily_revenue.sql', [
        (
            'FROM intermediate.int_order_products o\nGROUP BY 1, 2',
            'FROM intermediate.int_order_products o\nWHERE o.order_timestamp BETWEEN @start_ds AND @end_ds\nGROUP BY 1, 2'
        ),
    ])

    # Fix 4: top_products wrong model reference
    print("[4/6] Fixing top_products.sql upstream reference")
    fix_file('/app/models/analytics/top_products.sql', [
        ('intermediate.order_products', 'intermediate.int_order_products'),
    ])

    # Fix 5: Audit logic inversion — >= 0 (finds good rows) -> < 0 (finds bad rows)
    print("[5/6] Fixing audit logic in revenue_checks.sql")
    fix_file('/app/audits/revenue_checks.sql', [
        ('total_revenue >= 0', 'total_revenue < 0'),
    ])

    # Fix 6: Test expected output column names
    # In YAML, list items start with '      - key:' (6 spaces + '- '),
    # while continuation keys use '        key:' (8 spaces).
    # 'date:' starts each output row as a list item, so uses '- ' prefix.
    # Process revenue->total_revenue FIRST to avoid matching 'revenue' in
    # 'revenue_date' if we renamed date first.
    print("[6/6] Fixing test column names in test_daily_revenue.yaml")
    fix_file('/app/tests/test_daily_revenue.yaml', [
        ('        revenue: ', '        total_revenue: '),
        ('      - date: ', '      - revenue_date: '),
        ('        num_orders: ', '        order_count: '),
    ])

    print("\nAll fixes applied successfully.")


if __name__ == '__main__':
    main()
