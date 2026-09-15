
"""Tests for the dbt manifest diff-aware selector engine with lineage visualization."""

import json
import os

import pytest


RESULTS_PATH = "/app/results.json"

EXPECTED = {
    1: [
        "model.analytics.stg_users",
    ],
    2: [
        "model.analytics.fct_marketing",
        "model.analytics.int_campaign_performance",
        "model.analytics.int_user_attribution",
        "model.analytics.rpt_campaign_roi",
        "model.analytics.stg_ad_spend",
        "model.analytics.stg_campaigns",
    ],
    3: [
        "model.analytics.dim_products",
        "model.analytics.dim_users",
        "model.analytics.fct_orders",
        "model.analytics.int_product_categories",
        "model.analytics.int_transaction_items",
        "model.analytics.int_user_sessions",
        "model.analytics.stg_events",
        "model.analytics.stg_products",
        "model.analytics.stg_transactions",
        "model.analytics.stg_users",
        "seed.analytics.raw_events",
        "seed.analytics.raw_products",
        "seed.analytics.raw_transactions",
        "seed.analytics.raw_users",
    ],
    4: [
        "model.analytics.fct_revenue",
        "model.analytics.rpt_campaign_roi",
        "model.analytics.rpt_daily_revenue",
        "model.analytics.rpt_executive_dashboard",
        "model.analytics.rpt_user_ltv",
        "test.analytics.not_null_fct_revenue_amount.d7e8f9a0b1",
        "test.analytics.not_null_rpt_daily_revenue_date.f8a9b0c1d2",
        "test.analytics.relationships_fct_revenue_product_id__dim_products.c2d3e4f5a6",
        "test.analytics.unique_rpt_executive_dashboard_date.e3f4a5b6c7",
    ],
    5: [
        "model.analytics.dim_users",
        "model.analytics.int_user_sessions",
        "model.analytics.stg_events",
        "model.analytics.stg_users",
        "seed.analytics.raw_users",
    ],
    6: [
        "model.analytics.dim_products",
        "model.analytics.fct_orders",
        "model.analytics.fct_revenue",
        "test.analytics.not_null_dim_products_product_id.b6c7d8e9f0",
        "test.analytics.relationships_fct_revenue_product_id__dim_products.c2d3e4f5a6",
    ],
    7: [
        "model.analytics.dim_users",
        "model.analytics.fct_marketing",
        "model.analytics.fct_orders",
        "model.analytics.int_event_funnel",
        "model.analytics.int_user_attribution",
        "model.analytics.int_user_sessions",
        "model.analytics.rpt_campaign_roi",
        "model.analytics.rpt_daily_revenue",
        "model.analytics.rpt_executive_dashboard",
        "model.analytics.rpt_user_ltv",
        "model.analytics.stg_event_metadata",
        "model.analytics.stg_events",
        "seed.analytics.raw_events",
        "test.analytics.not_null_fct_marketing_attribution_id.b7c8d9e0f1",
        "test.analytics.not_null_fct_orders_order_id.a2b3c4d5e6",
        "test.analytics.not_null_int_event_funnel_step.d8e9f0a1b2",
        "test.analytics.not_null_rpt_daily_revenue_date.f8a9b0c1d2",
        "test.analytics.relationships_fct_orders_user_id__dim_users.e2f3a4b5c6",
        "test.analytics.unique_dim_users_user_id.c1d2e3f4a5",
        "test.analytics.unique_fct_orders_order_id.f7a8b9c0d1",
        "test.analytics.unique_rpt_executive_dashboard_date.e3f4a5b6c7",
    ],
    8: [
        "model.analytics.dim_products",
        "model.analytics.dim_users",
        "model.analytics.fct_orders",
        "model.analytics.fct_revenue",
    ],
    9: [
        "model.analytics.stg_ad_spend",
        "model.analytics.stg_campaigns",
        "model.analytics.stg_event_metadata",
        "model.analytics.stg_events",
        "model.analytics.stg_products",
        "model.analytics.stg_transactions",
        "model.analytics.stg_users",
    ],
    10: [
        "model.analytics.fct_marketing",
        "model.analytics.fct_orders",
        "model.analytics.fct_revenue",
    ],
    11: [
        "model.analytics.fct_marketing",
    ],
    12: [
        "model.analytics.rpt_daily_revenue",
        "model.analytics.rpt_executive_dashboard",
        "model.analytics.rpt_user_ltv",
    ],
    13: [
        "seed.analytics.raw_ad_spend",
        "seed.analytics.raw_campaigns",
        "seed.analytics.raw_events",
        "seed.analytics.raw_products",
        "seed.analytics.raw_transactions",
        "seed.analytics.raw_users",
    ],
    14: [
        "model.analytics.dim_products",
        "model.analytics.dim_users",
        "model.analytics.fct_orders",
        "model.analytics.fct_revenue",
        "model.analytics.int_product_categories",
        "model.analytics.int_transaction_items",
        "model.analytics.int_user_sessions",
        "model.analytics.rpt_daily_revenue",
        "model.analytics.rpt_executive_dashboard",
        "model.analytics.rpt_user_ltv",
        "model.analytics.stg_products",
        "model.analytics.stg_transactions",
        "model.analytics.stg_users",
        "seed.analytics.raw_ad_spend",
        "seed.analytics.raw_campaigns",
        "seed.analytics.raw_products",
        "seed.analytics.raw_transactions",
        "seed.analytics.raw_users",
    ],
    15: [
        "model.analytics.stg_ad_spend",
        "model.analytics.stg_campaigns",
        "model.analytics.stg_event_metadata",
        "model.analytics.stg_events",
        "model.analytics.stg_products",
        "model.analytics.stg_transactions",
        "model.analytics.stg_users",
    ],
    16: [
        "model.analytics.rpt_daily_revenue",
        "model.analytics.rpt_executive_dashboard",
        "model.analytics.rpt_user_ltv",
    ],
    17: [
        "model.analytics.dim_products",
        "model.analytics.dim_users",
    ],
    18: [
        "model.analytics.fct_marketing",
        "model.analytics.int_campaign_performance",
        "model.analytics.int_user_attribution",
        "model.analytics.rpt_campaign_roi",
        "model.analytics.rpt_executive_dashboard",
        "model.analytics.stg_ad_spend",
        "model.analytics.stg_campaigns",
        "test.analytics.accepted_values_stg_campaigns_channel.d6e7f8a9b0",
        "test.analytics.not_null_fct_marketing_attribution_id.b7c8d9e0f1",
        "test.analytics.not_null_int_campaign_performance_campaign_id.a3b4c5d6e7",
        "test.analytics.unique_rpt_executive_dashboard_date.e3f4a5b6c7",
    ],
    19: [
        "model.analytics.stg_event_metadata",
        "model.analytics.stg_events",
        "model.analytics.stg_products",
        "model.analytics.stg_transactions",
        "model.analytics.stg_users",
    ],
    20: [
        "model.analytics.dim_products",
        "model.analytics.dim_users",
        "model.analytics.fct_marketing",
        "model.analytics.fct_orders",
        "model.analytics.fct_revenue",
        "model.analytics.int_campaign_performance",
        "model.analytics.int_product_categories",
        "model.analytics.int_transaction_items",
        "model.analytics.int_user_attribution",
        "model.analytics.int_user_sessions",
        "model.analytics.rpt_daily_revenue",
        "model.analytics.rpt_executive_dashboard",
        "model.analytics.rpt_user_ltv",
        "model.analytics.stg_products",
        "model.analytics.stg_users",
    ],
    # === State comparison selectors ===
    21: [
        "model.analytics.int_event_funnel",
        "model.analytics.stg_event_metadata",
        "test.analytics.not_null_int_event_funnel_step.d8e9f0a1b2",
    ],
    22: [
        "model.analytics.fct_revenue",
        "model.analytics.rpt_executive_dashboard",
        "model.analytics.stg_campaigns",
    ],
    23: [
        "model.analytics.fct_marketing",
        "model.analytics.fct_revenue",
        "model.analytics.int_campaign_performance",
        "model.analytics.int_user_attribution",
        "model.analytics.rpt_campaign_roi",
        "model.analytics.rpt_daily_revenue",
        "model.analytics.rpt_executive_dashboard",
        "model.analytics.rpt_user_ltv",
        "model.analytics.stg_campaigns",
        "test.analytics.accepted_values_stg_campaigns_channel.d6e7f8a9b0",
        "test.analytics.not_null_fct_marketing_attribution_id.b7c8d9e0f1",
        "test.analytics.not_null_fct_revenue_amount.d7e8f9a0b1",
        "test.analytics.not_null_int_campaign_performance_campaign_id.a3b4c5d6e7",
        "test.analytics.not_null_rpt_daily_revenue_date.f8a9b0c1d2",
        "test.analytics.relationships_fct_revenue_product_id__dim_products.c2d3e4f5a6",
        "test.analytics.unique_rpt_executive_dashboard_date.e3f4a5b6c7",
    ],
    24: [
        "model.analytics.fct_revenue",
    ],
    25: [
        "model.analytics.dim_products",
        "model.analytics.dim_users",
        "model.analytics.fct_marketing",
        "model.analytics.fct_orders",
        "model.analytics.fct_revenue",
        "model.analytics.int_campaign_performance",
        "model.analytics.int_product_categories",
        "model.analytics.int_transaction_items",
        "model.analytics.int_user_attribution",
        "model.analytics.int_user_sessions",
        "model.analytics.rpt_campaign_roi",
        "model.analytics.rpt_daily_revenue",
        "model.analytics.rpt_executive_dashboard",
        "model.analytics.rpt_user_ltv",
        "model.analytics.stg_ad_spend",
        "model.analytics.stg_campaigns",
        "model.analytics.stg_events",
        "model.analytics.stg_products",
        "model.analytics.stg_transactions",
        "model.analytics.stg_users",
        "seed.analytics.raw_ad_spend",
        "seed.analytics.raw_campaigns",
        "seed.analytics.raw_events",
        "seed.analytics.raw_products",
        "seed.analytics.raw_transactions",
        "seed.analytics.raw_users",
    ],
}

QUERY_DESCRIPTIONS = {
    1: "simple name selector",
    2: "tag selector",
    3: "ancestor graph operator (+node)",
    4: "descendant graph operator (node+)",
    5: "N-hop ancestor operator (2+node)",
    6: "N-hop descendant operator (node+1)",
    7: "@ family-tree operator",
    8: "select with exclude",
    9: "path prefix selector",
    10: "config.materialized selector",
    11: "intersection (comma-separated)",
    12: "union (space-separated)",
    13: "resource_type selector",
    14: "complex select + exclude with graph ops",
    15: "fqn prefix selector",
    16: "YAML selector: union (nightly_run)",
    17: "YAML selector: intersection (mart_tables)",
    18: "YAML selector: method with descendants (marketing_pipeline)",
    19: "YAML selector: method with inline exclude (staging_no_marketing)",
    20: "YAML selector: cross-reference + graph ops (full_nightly)",
    21: "state:new selector",
    22: "state:modified selector",
    23: "state:modified with descendant graph operator",
    24: "state:modified intersected with tag:mart",
    25: "ancestors of state:modified nodes",
}


@pytest.fixture(scope="module")
def results():
    assert os.path.exists(RESULTS_PATH), (
        f"Results file not found at {RESULTS_PATH}. "
        "Did you run python3 /app/selector_engine.py?"
    )
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return {entry["id"]: entry["nodes"] for entry in data}


class TestResultsStructure:
    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_PATH)

    def test_results_is_valid_json(self):
        with open(RESULTS_PATH) as f:
            data = json.load(f)
        assert isinstance(data, list)

    def test_all_queries_present(self, results):
        for qid in EXPECTED:
            assert qid in results, f"Missing result for query {qid}"

    def test_results_are_sorted(self, results):
        for qid, nodes in results.items():
            assert nodes == sorted(nodes), (
                f"Query {qid}: nodes must be sorted alphabetically"
            )


class TestStringSelectors:
    @pytest.mark.parametrize("query_id", sorted(k for k in EXPECTED if k <= 15))
    def test_string_selector_query(self, results, query_id):
        desc = QUERY_DESCRIPTIONS.get(query_id, "")
        actual = results.get(query_id, [])
        expected = EXPECTED[query_id]

        actual_set = set(actual)
        expected_set = set(expected)

        missing = expected_set - actual_set
        extra = actual_set - expected_set

        assert actual == expected, (
            f"Query {query_id} ({desc}) mismatch.\n"
            f"  Expected {len(expected)} nodes, got {len(actual)}.\n"
            f"  Missing: {sorted(missing) if missing else 'none'}\n"
            f"  Extra:   {sorted(extra) if extra else 'none'}"
        )


class TestYamlSelectors:
    @pytest.mark.parametrize("query_id", sorted(k for k in EXPECTED if 16 <= k <= 20))
    def test_yaml_selector_query(self, results, query_id):
        desc = QUERY_DESCRIPTIONS.get(query_id, "")
        actual = results.get(query_id, [])
        expected = EXPECTED[query_id]

        actual_set = set(actual)
        expected_set = set(expected)

        missing = expected_set - actual_set
        extra = actual_set - expected_set

        assert actual == expected, (
            f"Query {query_id} ({desc}) mismatch.\n"
            f"  Expected {len(expected)} nodes, got {len(actual)}.\n"
            f"  Missing: {sorted(missing) if missing else 'none'}\n"
            f"  Extra:   {sorted(extra) if extra else 'none'}"
        )


class TestStateSelectors:
    @pytest.mark.parametrize("query_id", sorted(k for k in EXPECTED if k >= 21))
    def test_state_selector_query(self, results, query_id):
        desc = QUERY_DESCRIPTIONS.get(query_id, "")
        actual = results.get(query_id, [])
        expected = EXPECTED[query_id]

        actual_set = set(actual)
        expected_set = set(expected)

        missing = expected_set - actual_set
        extra = actual_set - expected_set

        assert actual == expected, (
            f"Query {query_id} ({desc}) mismatch.\n"
            f"  Expected {len(expected)} nodes, got {len(actual)}.\n"
            f"  Missing: {sorted(missing) if missing else 'none'}\n"
            f"  Extra:   {sorted(extra) if extra else 'none'}"
        )


class TestDOTOutput:
    def test_dot_file_exists(self):
        assert os.path.exists("/app/lineage.dot"), (
            "lineage.dot not found — selector_engine.py must produce /app/lineage.dot"
        )

    def test_dot_is_digraph(self):
        with open("/app/lineage.dot") as f:
            content = f.read()
        assert content.strip().startswith("digraph"), (
            "lineage.dot must start with 'digraph'"
        )

    def test_dot_contains_all_nodes(self):
        with open("/app/manifest.json") as f:
            manifest = json.load(f)
        with open("/app/lineage.dot") as f:
            content = f.read()
        for uid in manifest["nodes"]:
            assert f'"{uid}"' in content, (
                f"Node {uid} missing from DOT file"
            )

    def test_dot_edge_count(self):
        with open("/app/lineage.dot") as f:
            content = f.read()
        edge_count = content.count(" -> ")
        assert edge_count == 59, (
            f"Expected 59 edges in DOT file, found {edge_count}"
        )

    def test_dot_node_shapes(self):
        with open("/app/lineage.dot") as f:
            content = f.read()
        assert "shape=box" in content, "DOT must use shape=box for models"
        assert "shape=cylinder" in content, "DOT must use shape=cylinder for seeds"
        assert "shape=diamond" in content, "DOT must use shape=diamond for tests"

    def test_svg_exists_and_nonempty(self):
        assert os.path.exists("/app/lineage.svg"), (
            "lineage.svg not found — run dot -Tsvg /app/lineage.dot -o /app/lineage.svg"
        )
        assert os.path.getsize("/app/lineage.svg") > 0, (
            "lineage.svg is empty"
        )


class TestManifestAnalysis:
    @pytest.fixture(scope="class")
    def analysis(self):
        path = "/app/manifest_analysis.json"
        assert os.path.exists(path), (
            "manifest_analysis.json not found — "
            "run jq -f /app/analyze_manifest.jq /app/manifest.json > /app/manifest_analysis.json"
        )
        with open(path) as f:
            return json.load(f)

    def test_node_count(self, analysis):
        assert analysis["node_count"] == 44, (
            f"Expected node_count=44, got {analysis['node_count']}"
        )

    def test_by_resource_type(self, analysis):
        expected = {"model": 22, "seed": 6, "test": 16}
        assert analysis["by_resource_type"] == expected, (
            f"by_resource_type mismatch: expected {expected}, got {analysis['by_resource_type']}"
        )

    def test_root_nodes(self, analysis):
        expected = [
            "seed.analytics.raw_ad_spend",
            "seed.analytics.raw_campaigns",
            "seed.analytics.raw_events",
            "seed.analytics.raw_products",
            "seed.analytics.raw_transactions",
            "seed.analytics.raw_users",
        ]
        assert analysis["root_nodes"] == expected, (
            f"root_nodes mismatch: expected {expected}, got {analysis['root_nodes']}"
        )

    def test_leaf_nodes(self, analysis):
        expected = [
            "test.analytics.accepted_values_stg_campaigns_channel.d6e7f8a9b0",
            "test.analytics.accepted_values_stg_transactions_status.e1f2a3b4c5",
            "test.analytics.not_null_dim_products_product_id.b6c7d8e9f0",
            "test.analytics.not_null_fct_marketing_attribution_id.b7c8d9e0f1",
            "test.analytics.not_null_fct_orders_order_id.a2b3c4d5e6",
            "test.analytics.not_null_fct_revenue_amount.d7e8f9a0b1",
            "test.analytics.not_null_int_campaign_performance_campaign_id.a3b4c5d6e7",
            "test.analytics.not_null_int_event_funnel_step.d8e9f0a1b2",
            "test.analytics.not_null_rpt_daily_revenue_date.f8a9b0c1d2",
            "test.analytics.not_null_stg_users_user_id.f6a7b8c9d0",
            "test.analytics.relationships_fct_orders_user_id__dim_users.e2f3a4b5c6",
            "test.analytics.relationships_fct_revenue_product_id__dim_products.c2d3e4f5a6",
            "test.analytics.unique_dim_users_user_id.c1d2e3f4a5",
            "test.analytics.unique_fct_orders_order_id.f7a8b9c0d1",
            "test.analytics.unique_rpt_executive_dashboard_date.e3f4a5b6c7",
            "test.analytics.unique_stg_users_user_id.a1b2c3d4e5",
        ]
        assert analysis["leaf_nodes"] == expected, (
            f"leaf_nodes mismatch: expected {len(expected)} nodes, got {len(analysis['leaf_nodes'])}"
        )

    def test_max_fan_out(self, analysis):
        assert analysis["max_fan_out"] == 5, (
            f"Expected max_fan_out=5, got {analysis['max_fan_out']}"
        )

    def test_max_fan_out_nodes(self, analysis):
        expected = [
            "model.analytics.dim_users",
            "model.analytics.fct_orders",
            "model.analytics.fct_revenue",
            "model.analytics.stg_users",
        ]
        assert analysis["max_fan_out_nodes"] == expected, (
            f"max_fan_out_nodes mismatch: expected {expected}, got {analysis['max_fan_out_nodes']}"
        )

    def test_edge_count(self, analysis):
        assert analysis["edge_count"] == 59, (
            f"Expected edge_count=59, got {analysis['edge_count']}"
        )
