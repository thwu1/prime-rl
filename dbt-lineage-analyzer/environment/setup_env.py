#!/usr/bin/env python3
"""
Generate all data for the dbt pipeline forensics task.

Creates:
  /data/models/{staging,intermediate,marts,reporting}/*.sql  (current source)
  /data/manifest.json   (stale manifest from last successful build)
  /data/pipeline_runs.db (SQLite: 3 runs with different failure patterns)
  /data/selectors.yml    (CI selector definitions)
  /data/dbt_project.yml  (project config)
"""
import json
import os
import sqlite3

PROJECT = "analytics"

# ===================================================================
# SQL model file content (current source state)
# ===================================================================

SQL_MODELS = {
    # ---- Staging (source() calls) ----
    "staging/stg_customers": (
        "with source as (\n"
        "    select * from {{ source('raw', 'customers') }}\n"
        ")\n"
        "select\n"
        "    id as customer_id,\n"
        "    first_name,\n"
        "    last_name,\n"
        "    email,\n"
        "    created_at\n"
        "from source\n"
    ),
    "staging/stg_orders": (
        "with source as (\n"
        "    select * from {{ source('raw', 'orders') }}\n"
        ")\n"
        "select\n"
        "    id as order_id,\n"
        "    customer_id,\n"
        "    order_date,\n"
        "    status,\n"
        "    amount\n"
        "from source\n"
    ),
    "staging/stg_payments": (
        "with source as (\n"
        "    select * from {{ source('raw', 'payments') }}\n"
        ")\n"
        "select\n"
        "    id as payment_id,\n"
        "    order_id,\n"
        "    amount,\n"
        "    payment_method\n"
        "from source\n"
    ),
    "staging/stg_products": (
        "with source as (\n"
        "    select * from {{ source('raw', 'products') }}\n"
        ")\n"
        "select\n"
        "    id as product_id,\n"
        "    name,\n"
        "    category,\n"
        "    price\n"
        "from source\n"
    ),
    "staging/stg_inventory": (
        "with source as (\n"
        "    select * from {{ source('raw', 'inventory') }}\n"
        ")\n"
        "select\n"
        "    product_id,\n"
        "    warehouse_id,\n"
        "    quantity\n"
        "from source\n"
    ),
    "staging/stg_suppliers": (
        "with source as (\n"
        "    select * from {{ source('raw', 'suppliers') }}\n"
        ")\n"
        "select\n"
        "    id as supplier_id,\n"
        "    name,\n"
        "    region\n"
        "from source\n"
    ),
    # NEW model — not in stale manifest
    "staging/stg_regions": (
        "with source as (\n"
        "    select * from {{ source('raw', 'regions') }}\n"
        ")\n"
        "select\n"
        "    id as region_id,\n"
        "    name as region_name,\n"
        "    country\n"
        "from source\n"
    ),

    # ---- Intermediate (ref() calls) ----
    "intermediate/int_customer_orders": (
        "with customers as (\n"
        "    select * from {{ ref('stg_customers') }}\n"
        "),\n"
        "orders as (\n"
        "    select * from {{ ref('stg_orders') }}\n"
        ")\n"
        "select\n"
        "    customers.customer_id,\n"
        "    orders.order_id,\n"
        "    orders.order_date,\n"
        "    orders.amount\n"
        "from customers\n"
        "inner join orders on customers.customer_id = orders.customer_id\n"
    ),
    "intermediate/int_payment_methods": (
        "with payments as (\n"
        "    select * from {{ ref('stg_payments') }}\n"
        ")\n"
        "select\n"
        "    payment_id,\n"
        "    order_id,\n"
        "    payment_method,\n"
        "    amount\n"
        "from payments\n"
    ),
    "intermediate/int_product_inventory": (
        "with products as (\n"
        "    select * from {{ ref('stg_products') }}\n"
        "),\n"
        "inventory as (\n"
        "    select * from {{ ref('stg_inventory') }}\n"
        ")\n"
        "select\n"
        "    products.product_id,\n"
        "    products.name,\n"
        "    inventory.warehouse_id,\n"
        "    inventory.quantity\n"
        "from products\n"
        "inner join inventory on products.product_id = inventory.product_id\n"
    ),
    # EDGE CASE: SQL block comment contains a ref() that should be IGNORED
    "intermediate/int_supplier_products": (
        "/*\n"
        " * Historical note: this model previously joined\n"
        " * {{ ref('int_legacy_orders') }} for order context.\n"
        " * Removed during Q1 2024 refactoring.\n"
        " */\n"
        "with suppliers as (\n"
        "    select * from {{ ref('stg_suppliers') }}\n"
        "),\n"
        "products as (\n"
        "    select * from {{ ref('stg_products') }}\n"
        ")\n"
        "select\n"
        "    suppliers.supplier_id,\n"
        "    suppliers.name as supplier_name,\n"
        "    products.product_id,\n"
        "    products.name as product_name\n"
        "from suppliers\n"
        "cross join products\n"
    ),
    # NEW model — not in stale manifest
    "intermediate/int_regional_orders": (
        "with orders as (\n"
        "    select * from {{ ref('stg_orders') }}\n"
        "),\n"
        "regions as (\n"
        "    select * from {{ ref('stg_regions') }}\n"
        ")\n"
        "select\n"
        "    orders.order_id,\n"
        "    orders.customer_id,\n"
        "    regions.region_name,\n"
        "    orders.amount\n"
        "from orders\n"
        "inner join regions on orders.region_id = regions.region_id\n"
    ),
    # NEW model — not in stale manifest
    "intermediate/int_order_enriched": (
        "with customer_orders as (\n"
        "    select * from {{ ref('int_customer_orders') }}\n"
        "),\n"
        "payment_methods as (\n"
        "    select * from {{ ref('int_payment_methods') }}\n"
        "),\n"
        "regional as (\n"
        "    select * from {{ ref('int_regional_orders') }}\n"
        ")\n"
        "select\n"
        "    customer_orders.customer_id,\n"
        "    customer_orders.order_id,\n"
        "    payment_methods.payment_method,\n"
        "    regional.region_name,\n"
        "    customer_orders.amount\n"
        "from customer_orders\n"
        "left join payment_methods on customer_orders.order_id = payment_methods.order_id\n"
        "left join regional on customer_orders.order_id = regional.order_id\n"
    ),

    # ---- Marts ----
    # MODIFIED: added int_order_enriched as a new dependency
    "marts/fct_orders": (
        "{{\n"
        "    config(\n"
        "        materialized='table',\n"
        "        tags=['marts', 'daily']\n"
        "    )\n"
        "}}\n"
        "\n"
        "with customer_orders as (\n"
        "    select * from {{ ref('int_customer_orders') }}\n"
        "),\n"
        "payment_methods as (\n"
        "    select * from {{ ref('int_payment_methods') }}\n"
        "),\n"
        "enriched as (\n"
        "    select * from {{ ref('int_order_enriched') }}\n"
        ")\n"
        "select\n"
        "    customer_orders.order_id,\n"
        "    customer_orders.customer_id,\n"
        "    payment_methods.payment_method,\n"
        "    enriched.region_name,\n"
        "    customer_orders.amount\n"
        "from customer_orders\n"
        "left join payment_methods on customer_orders.order_id = payment_methods.order_id\n"
        "left join enriched on customer_orders.order_id = enriched.order_id\n"
    ),
    # EDGE CASE: comment contains a ref() call that should be IGNORED
    "marts/fct_payments": (
        "-- NOTE: Previously this model also joined with {{ ref('int_legacy_orders') }}\n"
        "-- That dependency was removed in the Q1 2024 refactoring.\n"
        "\n"
        "{{\n"
        "    config(\n"
        "        materialized='table',\n"
        "        tags=['marts', 'finance']\n"
        "    )\n"
        "}}\n"
        "\n"
        "with payments as (\n"
        "    select * from {{ ref('stg_payments') }}\n"
        "),\n"
        "methods as (\n"
        "    select * from {{ ref('int_payment_methods') }}\n"
        ")\n"
        "select\n"
        "    payments.payment_id,\n"
        "    payments.order_id,\n"
        "    methods.payment_method,\n"
        "    payments.amount\n"
        "from payments\n"
        "left join methods on payments.order_id = methods.order_id\n"
    ),
    # EDGE CASE: Jinja block comment contains a ref() that should be IGNORED
    "marts/fct_inventory_snapshots": (
        "{# Future enhancement: join with {{ ref('stg_warehouses') }} for location data #}\n"
        "{{\n"
        "    config(\n"
        "        materialized='table',\n"
        "        tags=['marts', 'inventory']\n"
        "    )\n"
        "}}\n"
        "\n"
        "with inventory as (\n"
        "    select * from {{ ref('int_product_inventory') }}\n"
        ")\n"
        "select\n"
        "    product_id,\n"
        "    warehouse_id,\n"
        "    quantity,\n"
        "    current_timestamp as snapshot_at\n"
        "from inventory\n"
    ),
    # NEW model — not in stale manifest
    "marts/fct_regional_sales": (
        "{{\n"
        "    config(\n"
        "        materialized='table',\n"
        "        tags=['marts', 'regional']\n"
        "    )\n"
        "}}\n"
        "\n"
        "with regional as (\n"
        "    select * from {{ ref('int_regional_orders') }}\n"
        "),\n"
        "enriched as (\n"
        "    select * from {{ ref('int_order_enriched') }}\n"
        ")\n"
        "select\n"
        "    regional.region_name,\n"
        "    sum(enriched.amount) as total_sales\n"
        "from regional\n"
        "join enriched on regional.order_id = enriched.order_id\n"
        "group by 1\n"
    ),
    # EDGE CASE: uses double quotes in ref() for first dependency
    "marts/dim_customers": (
        "{{\n"
        "    config(\n"
        "        materialized='table',\n"
        "        tags=['marts', 'core']\n"
        "    )\n"
        "}}\n"
        "\n"
        "with customers as (\n"
        "    select * from {{ ref('stg_customers') }}\n"
        "),\n"
        "orders as (\n"
        "    select * from {{ ref('int_customer_orders') }}\n"
        ")\n"
        "select\n"
        "    customers.customer_id,\n"
        "    customers.first_name,\n"
        "    customers.last_name,\n"
        "    count(orders.order_id) as order_count\n"
        "from customers\n"
        "left join orders on customers.customer_id = orders.customer_id\n"
        "group by 1, 2, 3\n"
    ),
    "marts/dim_products": (
        "{{\n"
        "    config(\n"
        "        materialized='table',\n"
        "        tags=['marts', 'core']\n"
        "    )\n"
        "}}\n"
        "\n"
        "with products as (\n"
        '    select * from {{ ref("stg_products") }}\n'
        "),\n"
        "supplier_products as (\n"
        "    select * from {{ ref('int_supplier_products') }}\n"
        ")\n"
        "select\n"
        "    products.product_id,\n"
        "    products.name,\n"
        "    products.category,\n"
        "    supplier_products.supplier_name\n"
        "from products\n"
        "left join supplier_products on products.product_id = supplier_products.product_id\n"
    ),

    # ---- Reporting ----
    "reporting/rpt_customer_lifetime_value": (
        "{{\n"
        "    config(\n"
        "        materialized='table',\n"
        "        tags=['reporting', 'weekly']\n"
        "    )\n"
        "}}\n"
        "\n"
        "with customers as (\n"
        "    select * from {{ ref('dim_customers') }}\n"
        "),\n"
        "orders as (\n"
        "    select * from {{ ref('fct_orders') }}\n"
        "),\n"
        "payments as (\n"
        "    select * from {{ ref('fct_payments') }}\n"
        ")\n"
        "select\n"
        "    customers.customer_id,\n"
        "    customers.first_name,\n"
        "    count(distinct orders.order_id) as total_orders,\n"
        "    sum(payments.amount) as lifetime_value\n"
        "from customers\n"
        "left join orders on customers.customer_id = orders.customer_id\n"
        "left join payments on orders.order_id = payments.order_id\n"
        "group by 1, 2\n"
    ),
    "reporting/rpt_daily_revenue": (
        "{{\n"
        "    config(\n"
        "        materialized='table',\n"
        "        tags=['reporting', 'daily']\n"
        "    )\n"
        "}}\n"
        "\n"
        "with orders as (\n"
        "    select * from {{ ref('fct_orders') }}\n"
        "),\n"
        "payments as (\n"
        "    select * from {{ ref('fct_payments') }}\n"
        ")\n"
        "select\n"
        "    orders.order_date,\n"
        "    count(distinct orders.order_id) as num_orders,\n"
        "    sum(payments.amount) as daily_revenue\n"
        "from orders\n"
        "left join payments on orders.order_id = payments.order_id\n"
        "group by 1\n"
    ),
    "reporting/rpt_product_performance": (
        "{{\n"
        "    config(\n"
        "        materialized='table',\n"
        "        tags=['reporting', 'weekly']\n"
        "    )\n"
        "}}\n"
        "\n"
        "with products as (\n"
        "    select * from {{ ref('dim_products') }}\n"
        "),\n"
        "inventory as (\n"
        "    select * from {{ ref('fct_inventory_snapshots') }}\n"
        ")\n"
        "select\n"
        "    products.product_id,\n"
        "    products.name,\n"
        "    inventory.quantity as current_stock\n"
        "from products\n"
        "left join inventory on products.product_id = inventory.product_id\n"
    ),
    # NEW model — not in stale manifest
    "reporting/rpt_regional_performance": (
        "{{\n"
        "    config(\n"
        "        materialized='table',\n"
        "        tags=['reporting', 'regional']\n"
        "    )\n"
        "}}\n"
        "\n"
        "with sales as (\n"
        "    select * from {{ ref('fct_regional_sales') }}\n"
        "),\n"
        "regions as (\n"
        "    select * from {{ ref('stg_regions') }}\n"
        ")\n"
        "select\n"
        "    regions.region_name,\n"
        "    regions.country,\n"
        "    sales.total_sales\n"
        "from sales\n"
        "join regions on sales.region_name = regions.region_name\n"
    ),
}

# ===================================================================
# Stale manifest definitions
# ===================================================================

# Model dependencies as they appear in the STALE manifest
# Does NOT include new models: stg_regions, int_regional_orders,
#   int_order_enriched, fct_regional_sales, rpt_regional_performance
# DOES include deleted model: int_legacy_orders
# fct_orders has OLD deps (missing int_order_enriched)
MANIFEST_MODEL_DEPS = {
    "stg_customers":    [f"seed.{PROJECT}.raw_customers"],
    "stg_orders":       [f"seed.{PROJECT}.raw_orders"],
    "stg_payments":     [f"seed.{PROJECT}.raw_payments"],
    "stg_products":     [f"seed.{PROJECT}.raw_products"],
    "stg_inventory":    [f"seed.{PROJECT}.raw_inventory"],
    "stg_suppliers":    [f"seed.{PROJECT}.raw_suppliers"],
    "int_customer_orders": [f"model.{PROJECT}.stg_customers",
                            f"model.{PROJECT}.stg_orders"],
    "int_payment_methods": [f"model.{PROJECT}.stg_payments"],
    "int_product_inventory": [f"model.{PROJECT}.stg_products",
                              f"model.{PROJECT}.stg_inventory"],
    "int_supplier_products": [f"model.{PROJECT}.stg_suppliers",
                              f"model.{PROJECT}.stg_products"],
    "int_legacy_orders": [f"model.{PROJECT}.stg_orders"],
    "fct_orders":       [f"model.{PROJECT}.int_customer_orders",
                         f"model.{PROJECT}.int_payment_methods"],
    "fct_payments":     [f"model.{PROJECT}.stg_payments",
                         f"model.{PROJECT}.int_payment_methods"],
    "fct_inventory_snapshots": [f"model.{PROJECT}.int_product_inventory"],
    "dim_customers":    [f"model.{PROJECT}.stg_customers",
                         f"model.{PROJECT}.int_customer_orders"],
    "dim_products":     [f"model.{PROJECT}.stg_products",
                         f"model.{PROJECT}.int_supplier_products"],
    "rpt_customer_lifetime_value": [f"model.{PROJECT}.dim_customers",
                                    f"model.{PROJECT}.fct_orders",
                                    f"model.{PROJECT}.fct_payments"],
    "rpt_daily_revenue": [f"model.{PROJECT}.fct_orders",
                          f"model.{PROJECT}.fct_payments"],
    "rpt_product_performance": [f"model.{PROJECT}.dim_products",
                                f"model.{PROJECT}.fct_inventory_snapshots"],
}

SEEDS = [
    "raw_customers", "raw_orders", "raw_payments",
    "raw_products", "raw_inventory", "raw_suppliers",
]

SINGLE_PARENT_TESTS = [
    ("unique_stg_customers_customer_id",    f"model.{PROJECT}.stg_customers"),
    ("not_null_stg_customers_customer_id",  f"model.{PROJECT}.stg_customers"),
    ("unique_stg_orders_order_id",          f"model.{PROJECT}.stg_orders"),
    ("not_null_stg_orders_order_id",        f"model.{PROJECT}.stg_orders"),
    ("unique_stg_payments_payment_id",      f"model.{PROJECT}.stg_payments"),
    ("not_null_stg_payments_payment_id",    f"model.{PROJECT}.stg_payments"),
    ("unique_stg_products_product_id",      f"model.{PROJECT}.stg_products"),
    ("unique_fct_orders_order_id",          f"model.{PROJECT}.fct_orders"),
    ("not_null_fct_orders_order_id",        f"model.{PROJECT}.fct_orders"),
    ("not_null_fct_orders_amount",          f"model.{PROJECT}.fct_orders"),
    ("unique_dim_customers_customer_id",    f"model.{PROJECT}.dim_customers"),
    ("unique_dim_products_product_id",      f"model.{PROJECT}.dim_products"),
    ("not_null_rpt_daily_revenue_date",     f"model.{PROJECT}.rpt_daily_revenue"),
    ("not_null_rpt_clv_customer_id",        f"model.{PROJECT}.rpt_customer_lifetime_value"),
    ("accepted_values_stg_payments_method", f"model.{PROJECT}.stg_payments"),
    ("not_null_fct_inv_snap_product_id",    f"model.{PROJECT}.fct_inventory_snapshots"),
]

MULTI_PARENT_TESTS = [
    ("relationships_fct_orders_customer_id__ref_dim_customers",
     [f"model.{PROJECT}.fct_orders", f"model.{PROJECT}.dim_customers"]),
    ("relationships_fct_payments_order_id__ref_fct_orders",
     [f"model.{PROJECT}.fct_payments", f"model.{PROJECT}.fct_orders"]),
    ("relationships_rpt_clv_customer_id__ref_dim_customers",
     [f"model.{PROJECT}.rpt_customer_lifetime_value",
      f"model.{PROJECT}.dim_customers"]),
    ("relationships_int_cust_orders_cid__ref_stg_customers",
     [f"model.{PROJECT}.int_customer_orders",
      f"model.{PROJECT}.stg_customers"]),
]

# ===================================================================
# Run result specifications (model statuses only; tests computed)
# ===================================================================

RUN_MODEL_STATUSES = {
    "run_001": {
        # Root cause 1: schema mismatch
        f"model.{PROJECT}.int_product_inventory":
            ("error", "Database Error in model int_product_inventory: "
             "column 'quantity_on_hand' does not exist"),
        # Root cause 2: compilation error (manifest drift — source SQL
        # now refs int_order_enriched which isn't registered)
        f"model.{PROJECT}.fct_orders":
            ("error", "Compilation Error in model fct_orders: "
             "encountered an error during compilation"),
        # Cascade from int_product_inventory
        f"model.{PROJECT}.fct_inventory_snapshots":
            ("skipped", "SKIP: upstream model int_product_inventory errored"),
        f"model.{PROJECT}.rpt_product_performance":
            ("skipped", "SKIP: upstream model fct_inventory_snapshots skipped"),
        # Cascade from fct_orders
        f"model.{PROJECT}.rpt_daily_revenue":
            ("skipped", "SKIP: upstream model fct_orders errored"),
        f"model.{PROJECT}.rpt_customer_lifetime_value":
            ("skipped", "SKIP: upstream model fct_orders errored"),
    },
    "run_002": {
        # Root cause 1: still broken
        f"model.{PROJECT}.int_product_inventory":
            ("error", "Database Error in model int_product_inventory: "
             "column 'quantity_on_hand' does not exist"),
        # Root cause 2: NEW transient failure in stg_payments
        f"model.{PROJECT}.stg_payments":
            ("error", "Database Error in model stg_payments: "
             "could not open relation 'raw.payments'"),
        # Cascade from stg_payments
        f"model.{PROJECT}.int_payment_methods":
            ("error", "Compilation Error: depends on model stg_payments "
             "which errored"),
        # fct_orders: STILL has its own compilation error, BUT now also
        # has failed upstream (int_payment_methods). This MASKS it as a
        # cascade failure in standard root-cause analysis.
        f"model.{PROJECT}.fct_orders":
            ("error", "Compilation Error in model fct_orders: "
             "encountered an error during compilation"),
        # Cascade from stg_payments
        f"model.{PROJECT}.fct_payments":
            ("error", "Compilation Error: depends on model stg_payments "
             "which errored"),
        # Cascade from int_product_inventory
        f"model.{PROJECT}.fct_inventory_snapshots":
            ("skipped", "SKIP: upstream model int_product_inventory errored"),
        f"model.{PROJECT}.rpt_product_performance":
            ("skipped", "SKIP: upstream model fct_inventory_snapshots skipped"),
        # Cascade from fct_orders
        f"model.{PROJECT}.rpt_daily_revenue":
            ("skipped", "SKIP: upstream model fct_orders errored"),
        f"model.{PROJECT}.rpt_customer_lifetime_value":
            ("skipped", "SKIP: upstream model fct_orders errored"),
    },
    "run_003": {
        # int_product_inventory FIXED, stg_payments RECOVERED
        # Only fct_orders remains broken (persistent manifest drift)
        f"model.{PROJECT}.fct_orders":
            ("error", "Compilation Error in model fct_orders: "
             "encountered an error during compilation"),
        # Cascade from fct_orders
        f"model.{PROJECT}.rpt_daily_revenue":
            ("skipped", "SKIP: upstream model fct_orders errored"),
        f"model.{PROJECT}.rpt_customer_lifetime_value":
            ("skipped", "SKIP: upstream model fct_orders errored"),
    },
}

# ===================================================================
# Generation functions
# ===================================================================

def write_sql_models():
    """Write current SQL model files to /data/models/."""
    for path, sql in SQL_MODELS.items():
        filepath = f"/data/models/{path}.sql"
        with open(filepath, "w") as f:
            f.write(sql)


def make_node(uid, name, resource_type, depends_on, fqn,
              tags=None, file_path=None):
    """Build a manifest node dict."""
    return {
        "unique_id": uid,
        "name": name,
        "resource_type": resource_type,
        "depends_on": {"nodes": depends_on},
        "fqn": fqn,
        "tags": tags or [],
        "original_file_path": file_path or f"models/{name}.sql",
        "package_name": PROJECT,
        "config": {
            "materialized": (
                "seed" if resource_type == "seed"
                else "table" if resource_type == "model"
                     and any(x in name for x in ("fct_", "dim_", "rpt_"))
                else "view"
            )
        },
    }


def write_manifest():
    """Write stale manifest.json to /data/."""
    nodes = {}

    # Seeds
    for s in SEEDS:
        uid = f"seed.{PROJECT}.{s}"
        nodes[uid] = make_node(
            uid, s, "seed", [], [PROJECT, s],
            file_path=f"seeds/{s}.csv",
        )

    # Models
    for name, deps in MANIFEST_MODEL_DEPS.items():
        uid = f"model.{PROJECT}.{name}"
        layer = ("staging" if name.startswith("stg_") else
                 "intermediate" if name.startswith("int_") else
                 "reporting" if name.startswith("rpt_") else "marts")
        tags = [layer]
        if "inventory" in name:
            tags.append("inventory")
        nodes[uid] = make_node(
            uid, name, "model", deps, [PROJECT, layer, name],
            tags=tags,
            file_path=f"models/{layer}/{name}.sql",
        )

    # Single-parent tests
    for tname, parent in SINGLE_PARENT_TESTS:
        uid = f"test.{PROJECT}.{tname}.abc123"
        nodes[uid] = make_node(
            uid, tname, "test", [parent], [PROJECT, tname],
            file_path=f"tests/{tname}.sql",
        )

    # Multi-parent tests
    for tname, parents in MULTI_PARENT_TESTS:
        uid = f"test.{PROJECT}.{tname}.def456"
        nodes[uid] = make_node(
            uid, tname, "test", parents, [PROJECT, tname],
            file_path=f"tests/{tname}.sql",
        )

    # Build child_map
    child_map = {uid: [] for uid in nodes}
    for uid, node in nodes.items():
        for dep in node["depends_on"]["nodes"]:
            if dep in child_map:
                child_map[dep].append(uid)

    # Build parent_map
    parent_map = {
        uid: list(node["depends_on"]["nodes"])
        for uid, node in nodes.items()
    }

    manifest = {
        "nodes": nodes,
        "child_map": child_map,
        "parent_map": parent_map,
        "sources": {},
        "metadata": {
            "dbt_schema_version":
                "https://schemas.getdbt.com/dbt/manifest/v11/manifest.json",
            "dbt_version": "1.7.0",
            "generated_at": "2024-06-01T10:30:00Z",
            "project_name": PROJECT,
        },
    }
    with open("/data/manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)


def compute_test_status(test_node, model_statuses):
    """Derive test status from parent model statuses."""
    has_error = False
    has_skipped = False
    for parent in test_node["depends_on"]["nodes"]:
        st = model_statuses.get(parent, ("pass", ""))[0]
        if st == "error":
            has_error = True
        elif st == "skipped":
            has_skipped = True
    if has_error:
        return "error", "depends on a model that errored"
    if has_skipped:
        return "skipped", "depends on a model that was skipped"
    return "pass", ""


def write_sqlite_db():
    """Write pipeline_runs.db to /data/."""
    with open("/data/manifest.json") as f:
        manifest = json.load(f)
    nodes = manifest["nodes"]

    db_path = "/data/pipeline_runs.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE runs (
        run_id TEXT PRIMARY KEY,
        started_at TEXT,
        completed_at TEXT
    )""")
    c.execute("""CREATE TABLE node_results (
        run_id TEXT,
        unique_id TEXT,
        status TEXT,
        message TEXT,
        execution_time REAL,
        PRIMARY KEY (run_id, unique_id)
    )""")

    run_dates = {
        "run_001": ("2024-06-10T02:00:00Z", "2024-06-10T02:15:00Z"),
        "run_002": ("2024-06-11T02:00:00Z", "2024-06-11T02:18:00Z"),
        "run_003": ("2024-06-12T02:00:00Z", "2024-06-12T02:12:00Z"),
    }
    for run_id, (s, e) in run_dates.items():
        c.execute("INSERT INTO runs VALUES (?,?,?)", (run_id, s, e))

    for run_id, model_statuses in RUN_MODEL_STATUSES.items():
        # Compute test statuses
        all_statuses = dict(model_statuses)
        for uid, node in nodes.items():
            if node["resource_type"] == "test":
                st, msg = compute_test_status(node, model_statuses)
                all_statuses[uid] = (st, msg)

        # Insert all node results
        for uid in nodes:
            if uid in all_statuses:
                st, msg = all_statuses[uid]
                et = 0.0 if st != "pass" else 1.5
            else:
                st, msg, et = "pass", "", 1.5
            c.execute("INSERT INTO node_results VALUES (?,?,?,?,?)",
                      (run_id, uid, st, msg, et))

    conn.commit()
    conn.close()


def write_selectors():
    """Write selectors.yml to /data/."""
    with open("/data/selectors.yml", "w") as f:
        f.write(
            "selectors:\n"
            "  - name: nightly_full\n"
            "    definition:\n"
            "      method: fqn\n"
            '      value: "*"\n'
            "  - name: orders_pipeline\n"
            "    definition:\n"
            "      method: fqn\n"
            '      value: "int_legacy_orders+"\n'
            "  - name: inventory_pipeline\n"
            "    definition:\n"
            "      method: tag\n"
            '      value: "inventory"\n'
            "  - name: payments_selective\n"
            "    definition:\n"
            "      method: fqn\n"
            '      value: "+fct_payments"\n'
            "  - name: supplier_analysis\n"
            "    definition:\n"
            "      method: fqn\n"
            '      value: "rpt_supplier_performance+"\n'
        )


def write_project_config():
    """Write dbt_project.yml to /data/."""
    with open("/data/dbt_project.yml", "w") as f:
        f.write(
            "name: analytics\n"
            "version: '1.0.0'\n"
            "config-version: 2\n"
            "profile: analytics\n"
            "\n"
            "model-paths: [\"models\"]\n"
            "test-paths: [\"tests\"]\n"
            "seed-paths: [\"seeds\"]\n"
            "target-path: \"target\"\n"
            "clean-targets:\n"
            "  - \"target\"\n"
            "  - \"dbt_packages\"\n"
        )


def main():
    for d in ["/data/models/staging", "/data/models/intermediate",
              "/data/models/marts", "/data/models/reporting"]:
        os.makedirs(d, exist_ok=True)
    os.makedirs("/app", exist_ok=True)

    write_sql_models()
    print("  SQL models written")
    write_manifest()
    print("  manifest.json written")
    write_sqlite_db()
    print("  pipeline_runs.db written")
    write_selectors()
    print("  selectors.yml written")
    write_project_config()
    print("  dbt_project.yml written")
    print("Data generation complete.")


if __name__ == "__main__":
    main()
