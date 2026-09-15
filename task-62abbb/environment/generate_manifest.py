#!/usr/bin/env python3
"""Generate a realistic dbt manifest.json and manifest_previous.json for the selector engine task."""

import copy
import hashlib
import json

PACKAGE = "analytics"
DATABASE = "postgres"
SCHEMA = "public"
BASE_TIME = 1687942823.0


def _checksum(name):
    return hashlib.sha256(name.encode()).hexdigest()


def make_seed_node(name, path, fqn):
    uid = f"seed.{PACKAGE}.{name}"
    return uid, {
        "unique_id": uid,
        "name": name,
        "resource_type": "seed",
        "package_name": PACKAGE,
        "path": path,
        "original_file_path": path,
        "fqn": fqn,
        "alias": name,
        "checksum": {"name": "sha256", "checksum": _checksum(uid)},
        "config": {
            "enabled": True,
            "alias": None,
            "schema": None,
            "database": None,
            "tags": [],
            "meta": {},
            "materialized": "seed",
            "incremental_strategy": None,
            "persist_docs": {},
            "quoting": {},
            "column_types": {},
            "full_refresh": None,
            "unique_key": None,
            "on_schema_change": "ignore",
            "grants": {},
            "packages": [],
            "docs": {"show": True, "node_color": None},
            "contract": {"enforced": False},
            "post-hook": [],
            "pre-hook": [],
            "quote_columns": None,
            "group": None,
        },
        "tags": [],
        "description": "",
        "columns": {},
        "meta": {},
        "group": None,
        "docs": {"show": True, "node_color": None},
        "depends_on": {"macros": []},
        "compiled_path": None,
        "build_path": None,
        "deferred": False,
        "unrendered_config": {},
        "created_at": BASE_TIME,
        "relation_name": f'"{DATABASE}"."{SCHEMA}"."{name}"',
        "raw_code": "",
        "root_path": f"/opt/dbt/{PACKAGE}",
        "database": DATABASE,
        "schema": SCHEMA,
    }


def make_model_node(name, path, fqn, tags, materialized, depends_on):
    uid = f"model.{PACKAGE}.{name}"
    return uid, {
        "unique_id": uid,
        "name": name,
        "resource_type": "model",
        "package_name": PACKAGE,
        "path": path,
        "original_file_path": path,
        "fqn": fqn,
        "alias": name,
        "checksum": {"name": "sha256", "checksum": _checksum(uid)},
        "config": {
            "enabled": True,
            "alias": None,
            "schema": None,
            "database": None,
            "tags": list(tags),
            "meta": {},
            "materialized": materialized,
            "incremental_strategy": "delete+insert" if materialized == "incremental" else None,
            "persist_docs": {},
            "quoting": {},
            "column_types": {},
            "full_refresh": None,
            "unique_key": None,
            "on_schema_change": "ignore",
            "grants": {},
            "packages": [],
            "docs": {"show": True, "node_color": None},
            "contract": {"enforced": False},
            "post-hook": [],
            "pre-hook": [],
            "group": None,
        },
        "tags": list(tags),
        "description": "",
        "columns": {},
        "meta": {},
        "group": None,
        "docs": {"show": True, "node_color": None},
        "depends_on": {"macros": [], "nodes": list(depends_on)},
        "compiled_path": None,
        "build_path": None,
        "deferred": False,
        "unrendered_config": {"materialized": materialized, "tags": list(tags)},
        "created_at": BASE_TIME + 0.001,
        "relation_name": f'"{DATABASE}"."{SCHEMA}"."{name}"',
        "raw_code": f"-- model {name}",
        "language": "sql",
        "refs": [],
        "sources": [],
        "metrics": [],
        "constraints": [],
        "contract": {"checksum": None, "enforced": False},
        "access": "protected",
        "version": None,
        "latest_version": None,
        "database": DATABASE,
        "schema": SCHEMA,
    }


def make_test_node(test_name, hash_suffix, depends_on):
    uid = f"test.{PACKAGE}.{test_name}.{hash_suffix}"
    return uid, {
        "unique_id": uid,
        "name": test_name,
        "resource_type": "test",
        "package_name": PACKAGE,
        "path": f"tests/{test_name}.sql",
        "original_file_path": f"tests/{test_name}.sql",
        "fqn": [PACKAGE, test_name],
        "alias": test_name,
        "checksum": {"name": "sha256", "checksum": _checksum(uid)},
        "config": {
            "enabled": True,
            "alias": None,
            "schema": None,
            "database": None,
            "tags": [],
            "meta": {},
            "materialized": "test",
            "severity": "ERROR",
            "store_failures": None,
            "where": None,
            "limit": None,
            "fail_calc": "count(*)",
            "warn_if": "!= 0",
            "error_if": "!= 0",
        },
        "tags": [],
        "description": "",
        "columns": {},
        "meta": {},
        "group": None,
        "docs": {"show": True, "node_color": None},
        "depends_on": {"macros": [], "nodes": list(depends_on)},
        "compiled_path": None,
        "build_path": None,
        "deferred": False,
        "unrendered_config": {"severity": "ERROR"},
        "created_at": BASE_TIME + 0.002,
        "raw_code": f"-- test {test_name}",
        "language": "sql",
        "refs": [],
        "sources": [],
        "metrics": [],
        "database": DATABASE,
        "schema": SCHEMA,
        "test_metadata": {
            "name": test_name.split("_")[0],
            "kwargs": {},
        },
    }


def build_manifest():
    nodes = {}

    # === Seeds ===
    seeds = [
        ("raw_users", "seeds/raw_users.csv", [PACKAGE, "raw_users"]),
        ("raw_events", "seeds/raw_events.csv", [PACKAGE, "raw_events"]),
        ("raw_products", "seeds/raw_products.csv", [PACKAGE, "raw_products"]),
        ("raw_transactions", "seeds/raw_transactions.csv", [PACKAGE, "raw_transactions"]),
        ("raw_campaigns", "seeds/raw_campaigns.csv", [PACKAGE, "raw_campaigns"]),
        ("raw_ad_spend", "seeds/raw_ad_spend.csv", [PACKAGE, "raw_ad_spend"]),
    ]
    for name, path, fqn in seeds:
        uid, node = make_seed_node(name, path, fqn)
        nodes[uid] = node

    # === Staging Models ===
    staging = [
        ("stg_users", "models/staging/stg_users.sql",
         [PACKAGE, "staging", "stg_users"], ["staging"], "view",
         ["seed.analytics.raw_users"]),
        ("stg_events", "models/staging/stg_events.sql",
         [PACKAGE, "staging", "stg_events"], ["staging"], "view",
         ["seed.analytics.raw_events"]),
        ("stg_event_metadata", "models/staging/stg_event_metadata.sql",
         [PACKAGE, "staging", "stg_event_metadata"], ["staging"], "view",
         ["seed.analytics.raw_events"]),
        ("stg_products", "models/staging/stg_products.sql",
         [PACKAGE, "staging", "stg_products"], ["staging"], "view",
         ["seed.analytics.raw_products"]),
        ("stg_transactions", "models/staging/stg_transactions.sql",
         [PACKAGE, "staging", "stg_transactions"], ["staging"], "view",
         ["seed.analytics.raw_transactions"]),
        ("stg_campaigns", "models/staging/stg_campaigns.sql",
         [PACKAGE, "staging", "stg_campaigns"], ["staging", "marketing"], "view",
         ["seed.analytics.raw_campaigns"]),
        ("stg_ad_spend", "models/staging/stg_ad_spend.sql",
         [PACKAGE, "staging", "stg_ad_spend"], ["staging", "marketing"], "view",
         ["seed.analytics.raw_ad_spend"]),
    ]
    for name, path, fqn, tags, mat, deps in staging:
        uid, node = make_model_node(name, path, fqn, tags, mat, deps)
        nodes[uid] = node

    # === Intermediate Models ===
    intermediate = [
        ("int_user_sessions", "models/intermediate/int_user_sessions.sql",
         [PACKAGE, "intermediate", "int_user_sessions"], ["intermediate"], "view",
         ["model.analytics.stg_users", "model.analytics.stg_events"]),
        ("int_event_funnel", "models/intermediate/int_event_funnel.sql",
         [PACKAGE, "intermediate", "int_event_funnel"], ["intermediate"], "view",
         ["model.analytics.stg_events", "model.analytics.stg_event_metadata"]),
        ("int_product_categories", "models/intermediate/int_product_categories.sql",
         [PACKAGE, "intermediate", "int_product_categories"], ["intermediate"], "view",
         ["model.analytics.stg_products"]),
        ("int_transaction_items", "models/intermediate/int_transaction_items.sql",
         [PACKAGE, "intermediate", "int_transaction_items"], ["intermediate"], "view",
         ["model.analytics.stg_transactions", "model.analytics.stg_products"]),
        ("int_campaign_performance", "models/intermediate/int_campaign_performance.sql",
         [PACKAGE, "intermediate", "int_campaign_performance"],
         ["intermediate", "marketing"], "view",
         ["model.analytics.stg_campaigns", "model.analytics.stg_ad_spend"]),
        ("int_user_attribution", "models/intermediate/int_user_attribution.sql",
         [PACKAGE, "intermediate", "int_user_attribution"],
         ["intermediate", "marketing"], "view",
         ["model.analytics.stg_users", "model.analytics.stg_events",
          "model.analytics.stg_campaigns"]),
    ]
    for name, path, fqn, tags, mat, deps in intermediate:
        uid, node = make_model_node(name, path, fqn, tags, mat, deps)
        nodes[uid] = node

    # === Mart Models ===
    marts = [
        ("dim_users", "models/marts/dim_users.sql",
         [PACKAGE, "marts", "dim_users"], ["mart"], "table",
         ["model.analytics.int_user_sessions", "model.analytics.stg_users"]),
        ("dim_products", "models/marts/dim_products.sql",
         [PACKAGE, "marts", "dim_products"], ["mart"], "table",
         ["model.analytics.int_product_categories", "model.analytics.stg_products"]),
        ("fct_orders", "models/marts/fct_orders.sql",
         [PACKAGE, "marts", "fct_orders"], ["mart"], "incremental",
         ["model.analytics.int_transaction_items", "model.analytics.dim_users",
          "model.analytics.dim_products"]),
        ("fct_revenue", "models/marts/fct_revenue.sql",
         [PACKAGE, "marts", "fct_revenue"], ["mart"], "incremental",
         ["model.analytics.int_transaction_items", "model.analytics.dim_products"]),
        ("fct_marketing", "models/marts/fct_marketing.sql",
         [PACKAGE, "marts", "fct_marketing"], ["mart", "marketing"], "incremental",
         ["model.analytics.int_campaign_performance",
          "model.analytics.int_user_attribution", "model.analytics.dim_users"]),
    ]
    for name, path, fqn, tags, mat, deps in marts:
        uid, node = make_model_node(name, path, fqn, tags, mat, deps)
        nodes[uid] = node

    # === Reporting Models ===
    reporting = [
        ("rpt_daily_revenue", "models/reporting/rpt_daily_revenue.sql",
         [PACKAGE, "reporting", "rpt_daily_revenue"], ["reporting", "nightly"],
         "table",
         ["model.analytics.fct_revenue", "model.analytics.fct_orders"]),
        ("rpt_user_ltv", "models/reporting/rpt_user_ltv.sql",
         [PACKAGE, "reporting", "rpt_user_ltv"], ["reporting", "nightly"],
         "table",
         ["model.analytics.dim_users", "model.analytics.fct_orders",
          "model.analytics.fct_revenue"]),
        ("rpt_campaign_roi", "models/reporting/rpt_campaign_roi.sql",
         [PACKAGE, "reporting", "rpt_campaign_roi"],
         ["reporting", "marketing", "weekly"], "table",
         ["model.analytics.fct_marketing", "model.analytics.fct_revenue"]),
        ("rpt_executive_dashboard", "models/reporting/rpt_executive_dashboard.sql",
         [PACKAGE, "reporting", "rpt_executive_dashboard"],
         ["reporting", "executive"], "table",
         ["model.analytics.rpt_daily_revenue", "model.analytics.rpt_user_ltv",
          "model.analytics.rpt_campaign_roi"]),
    ]
    for name, path, fqn, tags, mat, deps in reporting:
        uid, node = make_model_node(name, path, fqn, tags, mat, deps)
        nodes[uid] = node

    # === Tests ===
    tests = [
        ("unique_stg_users_user_id", "a1b2c3d4e5",
         ["model.analytics.stg_users"]),
        ("not_null_stg_users_user_id", "f6a7b8c9d0",
         ["model.analytics.stg_users"]),
        ("accepted_values_stg_transactions_status", "e1f2a3b4c5",
         ["model.analytics.stg_transactions"]),
        ("accepted_values_stg_campaigns_channel", "d6e7f8a9b0",
         ["model.analytics.stg_campaigns"]),
        ("unique_dim_users_user_id", "c1d2e3f4a5",
         ["model.analytics.dim_users"]),
        ("not_null_dim_products_product_id", "b6c7d8e9f0",
         ["model.analytics.dim_products"]),
        ("not_null_fct_orders_order_id", "a2b3c4d5e6",
         ["model.analytics.fct_orders"]),
        ("unique_fct_orders_order_id", "f7a8b9c0d1",
         ["model.analytics.fct_orders"]),
        ("relationships_fct_orders_user_id__dim_users", "e2f3a4b5c6",
         ["model.analytics.fct_orders", "model.analytics.dim_users"]),
        ("not_null_fct_revenue_amount", "d7e8f9a0b1",
         ["model.analytics.fct_revenue"]),
        ("relationships_fct_revenue_product_id__dim_products", "c2d3e4f5a6",
         ["model.analytics.fct_revenue", "model.analytics.dim_products"]),
        ("not_null_fct_marketing_attribution_id", "b7c8d9e0f1",
         ["model.analytics.fct_marketing"]),
        ("not_null_int_campaign_performance_campaign_id", "a3b4c5d6e7",
         ["model.analytics.int_campaign_performance"]),
        ("not_null_rpt_daily_revenue_date", "f8a9b0c1d2",
         ["model.analytics.rpt_daily_revenue"]),
        ("unique_rpt_executive_dashboard_date", "e3f4a5b6c7",
         ["model.analytics.rpt_executive_dashboard"]),
        ("not_null_int_event_funnel_step", "d8e9f0a1b2",
         ["model.analytics.int_event_funnel"]),
    ]
    for test_name, hash_suffix, deps in tests:
        uid, node = make_test_node(test_name, hash_suffix, deps)
        nodes[uid] = node

    # === Build child_map and parent_map ===
    child_map = {uid: [] for uid in nodes}
    parent_map = {uid: [] for uid in nodes}
    for uid, node in nodes.items():
        deps = node.get("depends_on", {}).get("nodes", [])
        parent_map[uid] = list(deps)
        for dep in deps:
            if dep in child_map:
                child_map[dep].append(uid)

    # Sort children for determinism
    for uid in child_map:
        child_map[uid] = sorted(child_map[uid])

    manifest = {
        "metadata": {
            "dbt_schema_version": "https://schemas.getdbt.com/dbt/manifest/v9/manifest.json",
            "dbt_version": "1.5.6",
            "generated_at": "2024-01-15T10:30:00.000000Z",
            "invocation_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "env": {},
            "project_id": "abcdef1234567890abcdef1234567890",
            "user_id": None,
            "send_anonymous_usage_stats": False,
            "adapter_type": "postgres",
        },
        "nodes": nodes,
        "sources": {},
        "macros": {},
        "docs": {},
        "exposures": {},
        "metrics": {},
        "groups": {},
        "selectors": {},
        "disabled": {},
        "parent_map": parent_map,
        "child_map": child_map,
        "group_map": {},
    }

    return manifest


def build_previous_manifest(current_manifest):
    """Build the previous-state manifest for state comparison.

    Differences from current:
    - REMOVED (state:new in current): stg_event_metadata, int_event_funnel,
      not_null_int_event_funnel_step test
    - MODIFIED (state:modified in current):
      - fct_revenue: different checksum (SQL body changed)
      - rpt_executive_dashboard: different depends_on (no rpt_campaign_roi dep)
      - stg_campaigns: different config/tags (was only ["staging"])
    """
    prev = copy.deepcopy(current_manifest)
    nodes = prev["nodes"]

    # Remove nodes that are "new" in the current manifest
    removed_uids = [
        "model.analytics.stg_event_metadata",
        "model.analytics.int_event_funnel",
        "test.analytics.not_null_int_event_funnel_step.d8e9f0a1b2",
    ]
    for uid in removed_uids:
        if uid in nodes:
            del nodes[uid]

    # Modify fct_revenue: different checksum (simulating SQL body change)
    fct_rev = nodes["model.analytics.fct_revenue"]
    fct_rev["checksum"]["checksum"] = _checksum("model.analytics.fct_revenue_v1")
    fct_rev["raw_code"] = "-- model fct_revenue (v1)"

    # Modify rpt_executive_dashboard: different depends_on (no rpt_campaign_roi)
    rpt_exec = nodes["model.analytics.rpt_executive_dashboard"]
    rpt_exec["depends_on"]["nodes"] = [
        "model.analytics.rpt_daily_revenue",
        "model.analytics.rpt_user_ltv",
    ]

    # Modify stg_campaigns: different tags (was only "staging", not "marketing")
    stg_camp = nodes["model.analytics.stg_campaigns"]
    stg_camp["tags"] = ["staging"]
    stg_camp["config"]["tags"] = ["staging"]
    stg_camp["unrendered_config"]["tags"] = ["staging"]

    # Rebuild child_map and parent_map for the previous manifest
    child_map = {uid: [] for uid in nodes}
    parent_map = {uid: [] for uid in nodes}
    for uid, node in nodes.items():
        deps = node.get("depends_on", {}).get("nodes", [])
        parent_map[uid] = [d for d in deps if d in nodes]
        for dep in deps:
            if dep in child_map:
                child_map[dep].append(uid)
    for uid in child_map:
        child_map[uid] = sorted(child_map[uid])

    prev["child_map"] = child_map
    prev["parent_map"] = parent_map

    return prev


if __name__ == "__main__":
    manifest = build_manifest()
    with open("/app/manifest.json", "w") as f:
        json.dump(manifest, f, indent=2, sort_keys=False)
    print(f"Generated manifest with {len(manifest['nodes'])} nodes")

    prev_manifest = build_previous_manifest(manifest)
    with open("/app/manifest_previous.json", "w") as f:
        json.dump(prev_manifest, f, indent=2, sort_keys=False)
    print(f"Generated previous manifest with {len(prev_manifest['nodes'])} nodes")
