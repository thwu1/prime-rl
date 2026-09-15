#!/usr/bin/env python3
"""Generate manifest.json and run_results.json for the pipeline analyzer task."""
import json
import os

PROJECT = "analytics"


def make_node(unique_id, name, resource_type, depends_on, fqn, tags=None, file_path=None):
    return {
        "unique_id": unique_id,
        "name": name,
        "resource_type": resource_type,
        "depends_on": {"nodes": depends_on},
        "fqn": fqn,
        "tags": tags or [],
        "original_file_path": file_path or f"models/{'/'.join(fqn[1:])}.sql",
        "package_name": PROJECT,
        "config": {
            "materialized": "table" if resource_type in ("seed", "snapshot") else "view"
        },
    }


nodes = {}

# Seeds
seeds = [
    "raw_customers",
    "raw_orders",
    "raw_payments",
    "raw_products",
    "raw_inventory",
    "raw_suppliers",
]
for s in seeds:
    uid = f"seed.{PROJECT}.{s}"
    nodes[uid] = make_node(
        uid, s, "seed", [], [PROJECT, s], file_path=f"seeds/{s}.csv"
    )

# Staging models
staging_deps = {
    "stg_customers": [f"seed.{PROJECT}.raw_customers"],
    "stg_orders": [f"seed.{PROJECT}.raw_orders"],
    "stg_payments": [f"seed.{PROJECT}.raw_payments"],
    "stg_products": [f"seed.{PROJECT}.raw_products"],
    "stg_inventory": [f"seed.{PROJECT}.raw_inventory"],
    "stg_suppliers": [f"seed.{PROJECT}.raw_suppliers"],
}
for name, deps in staging_deps.items():
    uid = f"model.{PROJECT}.{name}"
    nodes[uid] = make_node(
        uid, name, "model", deps, [PROJECT, "staging", name], tags=["staging"]
    )

# Intermediate models
intermediate_deps = {
    "int_customer_orders": [
        f"model.{PROJECT}.stg_customers",
        f"model.{PROJECT}.stg_orders",
    ],
    "int_payment_methods": [f"model.{PROJECT}.stg_payments"],
    "int_product_inventory": [
        f"model.{PROJECT}.stg_products",
        f"model.{PROJECT}.stg_inventory",
    ],
    "int_supplier_products": [
        f"model.{PROJECT}.stg_suppliers",
        f"model.{PROJECT}.stg_products",
    ],
}
for name, deps in intermediate_deps.items():
    uid = f"model.{PROJECT}.{name}"
    nodes[uid] = make_node(
        uid, name, "model", deps, [PROJECT, "intermediate", name], tags=["intermediate"]
    )

# Fact tables
fact_deps = {
    "fct_orders": [
        f"model.{PROJECT}.int_customer_orders",
        f"model.{PROJECT}.int_payment_methods",
    ],
    "fct_payments": [
        f"model.{PROJECT}.stg_payments",
        f"model.{PROJECT}.int_payment_methods",
    ],
    "fct_inventory_snapshots": [f"model.{PROJECT}.int_product_inventory"],
}
for name, deps in fact_deps.items():
    uid = f"model.{PROJECT}.{name}"
    sub = "finance" if "payment" in name else "core"
    nodes[uid] = make_node(
        uid, name, "model", deps, [PROJECT, "marts", sub, name], tags=["marts", "daily"]
    )

# Dimension tables
dim_deps = {
    "dim_customers": [
        f"model.{PROJECT}.stg_customers",
        f"model.{PROJECT}.int_customer_orders",
    ],
    "dim_products": [
        f"model.{PROJECT}.stg_products",
        f"model.{PROJECT}.int_supplier_products",
    ],
}
for name, deps in dim_deps.items():
    uid = f"model.{PROJECT}.{name}"
    nodes[uid] = make_node(
        uid, name, "model", deps, [PROJECT, "marts", "core", name], tags=["marts"]
    )

# Report tables
report_deps = {
    "rpt_customer_lifetime_value": [
        f"model.{PROJECT}.dim_customers",
        f"model.{PROJECT}.fct_orders",
        f"model.{PROJECT}.fct_payments",
    ],
    "rpt_daily_revenue": [
        f"model.{PROJECT}.fct_orders",
        f"model.{PROJECT}.fct_payments",
    ],
    "rpt_product_performance": [
        f"model.{PROJECT}.dim_products",
        f"model.{PROJECT}.fct_inventory_snapshots",
    ],
}
for name, deps in report_deps.items():
    uid = f"model.{PROJECT}.{name}"
    nodes[uid] = make_node(
        uid,
        name,
        "model",
        deps,
        [PROJECT, "marts", "reporting", name],
        tags=["marts", "reporting", "weekly"],
    )

# Single-parent tests
single_tests = [
    ("unique_stg_customers_customer_id", f"model.{PROJECT}.stg_customers"),
    ("not_null_stg_customers_customer_id", f"model.{PROJECT}.stg_customers"),
    ("unique_stg_orders_order_id", f"model.{PROJECT}.stg_orders"),
    ("not_null_stg_orders_order_id", f"model.{PROJECT}.stg_orders"),
    ("unique_stg_payments_payment_id", f"model.{PROJECT}.stg_payments"),
    ("not_null_stg_payments_payment_id", f"model.{PROJECT}.stg_payments"),
    ("unique_stg_products_product_id", f"model.{PROJECT}.stg_products"),
    ("unique_fct_orders_order_id", f"model.{PROJECT}.fct_orders"),
    ("not_null_fct_orders_order_id", f"model.{PROJECT}.fct_orders"),
    ("not_null_fct_orders_amount", f"model.{PROJECT}.fct_orders"),
    ("unique_dim_customers_customer_id", f"model.{PROJECT}.dim_customers"),
    ("unique_dim_products_product_id", f"model.{PROJECT}.dim_products"),
    ("not_null_rpt_daily_revenue_date", f"model.{PROJECT}.rpt_daily_revenue"),
    (
        "not_null_rpt_customer_lifetime_value_customer_id",
        f"model.{PROJECT}.rpt_customer_lifetime_value",
    ),
    ("accepted_values_stg_orders_status", f"model.{PROJECT}.stg_orders"),
    ("accepted_values_stg_payments_method", f"model.{PROJECT}.stg_payments"),
    (
        "not_null_fct_inventory_snapshots_product_id",
        f"model.{PROJECT}.fct_inventory_snapshots",
    ),
]
for tname, parent in single_tests:
    uid = f"test.{PROJECT}.{tname}.abc123"
    nodes[uid] = make_node(
        uid, tname, "test", [parent], [PROJECT, tname], file_path=f"tests/{tname}.sql"
    )

# Multi-parent (detached) tests
multi_tests = [
    (
        "relationships_fct_orders_customer_id__customer_id__ref_dim_customers",
        [f"model.{PROJECT}.fct_orders", f"model.{PROJECT}.dim_customers"],
    ),
    (
        "relationships_fct_payments_order_id__order_id__ref_fct_orders",
        [f"model.{PROJECT}.fct_payments", f"model.{PROJECT}.fct_orders"],
    ),
    (
        "relationships_rpt_clv_customer_id__customer_id__ref_dim_customers",
        [
            f"model.{PROJECT}.rpt_customer_lifetime_value",
            f"model.{PROJECT}.dim_customers",
        ],
    ),
    (
        "relationships_int_customer_orders_customer_id__customer_id__ref_stg_customers",
        [f"model.{PROJECT}.int_customer_orders", f"model.{PROJECT}.stg_customers"],
    ),
]
for tname, parents in multi_tests:
    uid = f"test.{PROJECT}.{tname}.def456"
    nodes[uid] = make_node(
        uid, tname, "test", parents, [PROJECT, tname], file_path=f"tests/{tname}.sql"
    )

# Build child_map and parent_map
child_map = {uid: [] for uid in nodes}
parent_map = {}
for uid, node in nodes.items():
    parent_map[uid] = list(node["depends_on"]["nodes"])
    for parent_uid in node["depends_on"]["nodes"]:
        if parent_uid in child_map:
            child_map[parent_uid].append(uid)

manifest = {
    "nodes": nodes,
    "child_map": child_map,
    "parent_map": parent_map,
    "sources": {},
    "metadata": {
        "dbt_schema_version": "https://schemas.getdbt.com/dbt/manifest/v11/manifest.json",
        "dbt_version": "1.7.0",
        "generated_at": "2024-01-15T10:30:00Z",
        "project_name": PROJECT,
    },
}

# Run results
failed_nodes = {
    # Root cause 1: stg_payments fails due to missing source table
    f"model.{PROJECT}.stg_payments": (
        "error",
        "Database Error: relation 'raw_payments' does not exist",
    ),
    # Downstream cascade from stg_payments
    f"model.{PROJECT}.int_payment_methods": (
        "error",
        "Compilation Error: depends on stg_payments which errored",
    ),
    f"model.{PROJECT}.fct_payments": (
        "error",
        "Compilation Error: depends on int_payment_methods which errored",
    ),
    f"model.{PROJECT}.fct_orders": (
        "error",
        "Compilation Error: depends on int_payment_methods which errored",
    ),
    f"model.{PROJECT}.rpt_daily_revenue": (
        "skipped",
        "SKIP: upstream model fct_orders errored",
    ),
    f"model.{PROJECT}.rpt_customer_lifetime_value": (
        "skipped",
        "SKIP: upstream model fct_orders errored",
    ),
    # Root cause 2: int_product_inventory fails due to schema mismatch
    f"model.{PROJECT}.int_product_inventory": (
        "error",
        "Database Error: column 'quantity_on_hand' does not exist",
    ),
    # Downstream cascade from int_product_inventory
    f"model.{PROJECT}.fct_inventory_snapshots": (
        "skipped",
        "SKIP: upstream model int_product_inventory errored",
    ),
    f"model.{PROJECT}.rpt_product_performance": (
        "skipped",
        "SKIP: upstream models errored",
    ),
}

failed_tests = {
    f"test.{PROJECT}.unique_stg_payments_payment_id.abc123": (
        "error",
        "depends on stg_payments which errored",
    ),
    f"test.{PROJECT}.not_null_stg_payments_payment_id.abc123": (
        "error",
        "depends on stg_payments which errored",
    ),
    f"test.{PROJECT}.accepted_values_stg_payments_method.abc123": (
        "error",
        "depends on stg_payments which errored",
    ),
    f"test.{PROJECT}.unique_fct_orders_order_id.abc123": (
        "error",
        "depends on fct_orders which errored",
    ),
    f"test.{PROJECT}.not_null_fct_orders_order_id.abc123": (
        "error",
        "depends on fct_orders which errored",
    ),
    f"test.{PROJECT}.not_null_fct_orders_amount.abc123": (
        "error",
        "depends on fct_orders which errored",
    ),
    f"test.{PROJECT}.not_null_rpt_daily_revenue_date.abc123": (
        "skipped",
        "depends on rpt_daily_revenue which was skipped",
    ),
    f"test.{PROJECT}.not_null_rpt_customer_lifetime_value_customer_id.abc123": (
        "skipped",
        "depends on rpt_customer_lifetime_value which was skipped",
    ),
    f"test.{PROJECT}.not_null_fct_inventory_snapshots_product_id.abc123": (
        "skipped",
        "depends on fct_inventory_snapshots which was skipped",
    ),
    f"test.{PROJECT}.relationships_fct_orders_customer_id__customer_id__ref_dim_customers.def456": (
        "error",
        "depends on fct_orders which errored",
    ),
    f"test.{PROJECT}.relationships_fct_payments_order_id__order_id__ref_fct_orders.def456": (
        "error",
        "depends on fct_payments and fct_orders which errored",
    ),
    f"test.{PROJECT}.relationships_rpt_clv_customer_id__customer_id__ref_dim_customers.def456": (
        "skipped",
        "depends on rpt_customer_lifetime_value which was skipped",
    ),
}

all_failed = {**failed_nodes, **failed_tests}

results = []
for uid in nodes:
    if uid in all_failed:
        status, msg = all_failed[uid]
        results.append(
            {"unique_id": uid, "status": status, "message": msg, "execution_time": 0.0}
        )
    else:
        results.append(
            {"unique_id": uid, "status": "pass", "message": "", "execution_time": 1.5}
        )

run_results = {
    "metadata": {
        "dbt_schema_version": "https://schemas.getdbt.com/dbt/run-results/v5/run-results.json",
        "dbt_version": "1.7.0",
        "generated_at": "2024-01-15T10:35:00Z",
    },
    "results": results,
    "elapsed_time": 45.0,
}

os.makedirs("/data", exist_ok=True)
with open("/data/manifest.json", "w") as f:
    json.dump(manifest, f, indent=2)
with open("/data/run_results.json", "w") as f:
    json.dump(run_results, f, indent=2)

print("Generated /data/manifest.json and /data/run_results.json")
