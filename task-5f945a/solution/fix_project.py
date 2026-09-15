#!/usr/bin/env python3
"""
Programmatically fix all 5 bugs in the dbt ecommerce analytics project.

Bug 1: Source schema + table name mismatch (source name 'raw_data' used as
       schema but seeds land in 'main'; table names lack 'raw_' prefix)
Bug 2: Integer division in cents_to_dollars macro truncates decimal values
Bug 3: Wrong join condition in mart_revenue_summary (item_id vs order_id)
Bug 4: Wrong status filter value ('complete' vs 'completed')
Bug 5: Incorrect unique test on order_date alone (grain is date+category)
"""

import os

PROJECT_DIR = "/app/dbt_project"


def read_file(relative_path):
    path = os.path.join(PROJECT_DIR, relative_path)
    with open(path) as f:
        return f.read()


def write_file(relative_path, content):
    path = os.path.join(PROJECT_DIR, relative_path)
    with open(path, "w") as f:
        f.write(content)


def fix_bug1_source_config():
    """
    Two issues in source configuration:
    1. Source name 'raw_data' is used by dbt as the schema name, but seeds
       are loaded into the default 'main' schema. Fix: add schema: main.
    2. Table names 'orders', 'order_items', 'products' don't match seed
       file names 'raw_orders', 'raw_order_items', 'raw_products'.
    Also update staging model source() references to use corrected names.
    """
    # Rewrite sources.yml with schema override and corrected table names
    sources_content = """version: 2

sources:
  - name: raw_data
    schema: main
    tables:
      - name: raw_orders
      - name: raw_order_items
      - name: raw_products
"""
    write_file("models/sources.yml", sources_content)

    # Fix staging model source references
    staging_fixes = {
        "models/staging/stg_orders.sql": ("'orders'", "'raw_orders'"),
        "models/staging/stg_order_items.sql": ("'order_items'", "'raw_order_items'"),
        "models/staging/stg_products.sql": ("'products'", "'raw_products'"),
    }
    for filepath, (old_name, new_name) in staging_fixes.items():
        content = read_file(filepath)
        content = content.replace(old_name, new_name)
        write_file(filepath, content)

    print("[Bug 1] Fixed source schema, table names, and staging model references")


def fix_bug2_integer_division():
    """
    The cents_to_dollars macro uses integer division (column / 100).
    In DuckDB, integer / integer yields integer, truncating decimals.
    1999 / 100 = 19 instead of 19.99. Fix by casting to DOUBLE.
    """
    content = read_file("macros/pricing.sql")
    content = content.replace(
        "({{ column_name }} / 100)",
        "(CAST({{ column_name }} AS DOUBLE) / 100.0)"
    )
    write_file("macros/pricing.sql", content)
    print("[Bug 2] Fixed integer division in cents_to_dollars macro")


def fix_bug3_wrong_join():
    """
    mart_revenue_summary joins stg_orders with int_order_revenue
    on o.order_id = r.item_id. Should be o.order_id = r.order_id.
    """
    content = read_file("models/marts/mart_revenue_summary.sql")
    content = content.replace("o.order_id = r.item_id", "o.order_id = r.order_id")
    write_file("models/marts/mart_revenue_summary.sql", content)
    print("[Bug 3] Fixed join condition in mart_revenue_summary")


def fix_bug4_status_filter():
    """
    mart_revenue_summary filters on status = 'complete' but the actual
    value in the data is 'completed'.
    """
    content = read_file("models/marts/mart_revenue_summary.sql")
    content = content.replace("= 'complete'", "= 'completed'")
    write_file("models/marts/mart_revenue_summary.sql", content)
    print("[Bug 4] Fixed status filter value ('complete' -> 'completed')")


def fix_bug5_uniqueness_test():
    """
    _marts.yml has a 'unique' test on order_date, but the mart's grain
    is (order_date, category). Remove the incorrect unique test.
    """
    content = read_file("models/marts/_marts.yml")
    content = content.replace("          - unique\n", "")
    write_file("models/marts/_marts.yml", content)
    print("[Bug 5] Removed incorrect unique test on order_date")


if __name__ == "__main__":
    fix_bug1_source_config()
    fix_bug2_integer_division()
    fix_bug3_wrong_join()
    fix_bug4_status_filter()
    fix_bug5_uniqueness_test()
    print("\nAll 5 bugs fixed. Run 'dbt build' to verify.")
