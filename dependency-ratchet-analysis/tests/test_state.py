
import json
import os
import sqlite3
import xml.etree.ElementTree as ET
from collections import defaultdict

import pytest

REPORT_PATH = "/app/analysis_report.json"
DB_PATH = "/app/deps.db"
SVG_PATH = "/app/graph.svg"

# ── Ground Truth ────────────────────────────────────────────────

LAYER_MAP = {
    "logging": 0, "config": 0, "crypto": 0, "http_client": 0,
    "database": 0, "metrics": 0,
    "payment_gateway": 1, "email_provider": 1, "sms_provider": 1,
    "storage_backend": 1,
    "merchants": 2, "customers": 2, "transactions": 2,
    "subscriptions": 2, "invoices": 2, "refunds": 2, "disputes": 2,
    "audit_log": 2,
    "api_merchants": 3, "api_transactions": 3, "api_subscriptions": 3,
    "api_webhooks": 3,
    "web_server": 4, "worker_service": 4, "cron_service": 4,
}

LAYER_NAMES = {0: "utility", 1: "power", 2: "business", 3: "api", 4: "services"}

EXPECTED_LEVELS = {
    "logging": "layered", "config": "layered_dag", "crypto": "dag",
    "http_client": "false", "database": "layered", "metrics": "layered",
    "payment_gateway": "layered", "email_provider": "false",
    "sms_provider": "layered", "storage_backend": "layered_dag",
    "merchants": "layered", "customers": "layered", "transactions": "layered",
    "subscriptions": "layered_dag", "invoices": "layered", "refunds": "dag",
    "disputes": "false", "audit_log": "layered",
    "api_merchants": "layered", "api_transactions": "layered",
    "api_subscriptions": "false", "api_webhooks": "layered",
    "web_server": "false", "worker_service": "false", "cron_service": "false",
}

PACKAGES_WITH_VIOLATIONS = {"logging", "sms_provider", "subscriptions"}

UPGRADEABLE_PACKAGES = {
    "http_client", "api_subscriptions", "web_server", "worker_service",
    "cron_service",
    "database", "metrics", "payment_gateway", "merchants", "customers",
    "transactions", "audit_log", "api_merchants", "api_transactions",
    "api_webhooks",
    "config", "storage_backend",
}

NON_UPGRADEABLE_PACKAGES = {
    "logging", "sms_provider",
    "email_provider", "disputes",
    "invoices", "subscriptions",
    "crypto", "refunds",
}

EXPECTED_TRANSITIVE_COUNTS = {
    "config": 0,
    "crypto": 1,
    "logging": 7,
    "http_client": 7,
    "database": 7,
    "metrics": 8,
    "payment_gateway": 7,
    "email_provider": 7,
    "sms_provider": 8,
    "storage_backend": 8,
    "merchants": 7,
    "customers": 8,
    "transactions": 9,
    "subscriptions": 11,
    "invoices": 11,
    "refunds": 10,
    "disputes": 12,
    "audit_log": 10,
    "api_merchants": 9,
    "api_transactions": 11,
    "api_subscriptions": 12,
    "api_webhooks": 10,
    "web_server": 17,
    "worker_service": 14,
    "cron_service": 12,
}

DIRECT_DEP_COUNTS = {
    "logging": 2, "config": 0, "crypto": 1, "http_client": 2,
    "database": 2, "metrics": 2, "payment_gateway": 4, "email_provider": 4,
    "sms_provider": 4, "storage_backend": 4, "merchants": 5, "customers": 4,
    "transactions": 6, "subscriptions": 6, "invoices": 6, "refunds": 5,
    "disputes": 8, "audit_log": 5, "api_merchants": 4, "api_transactions": 5,
    "api_subscriptions": 5, "api_webhooks": 5, "web_server": 7,
    "worker_service": 8, "cron_service": 6,
}

TOTAL_DIRECT_EDGES = sum(DIRECT_DEP_COUNTS.values())  # 110
TOTAL_TRANSITIVE_ROWS = sum(EXPECTED_TRANSITIVE_COUNTS.values())  # 223

# The full-graph SCC with 6 nodes
LARGE_SCC_MEMBERS = {
    "logging", "merchants", "database", "payment_gateway",
    "email_provider", "http_client"
}

SMALL_SCC_MEMBERS = {"subscriptions", "invoices"}

# Edges within the 6-node SCC (ground truth for FAS verification)
LARGE_SCC_EDGES = {
    ("logging", "merchants"),
    ("merchants", "database"),
    ("merchants", "logging"),
    ("merchants", "payment_gateway"),
    ("merchants", "email_provider"),
    ("database", "logging"),
    ("payment_gateway", "http_client"),
    ("payment_gateway", "logging"),
    ("email_provider", "http_client"),
    ("email_provider", "logging"),
    ("email_provider", "merchants"),
    ("http_client", "logging"),
}

SMALL_SCC_EDGES = {
    ("subscriptions", "invoices"),
    ("invoices", "subscriptions"),
}

# Coupling metrics ground truth
EXPECTED_AFFERENT = {
    "config": 24, "logging": 22, "http_client": 6, "database": 10,
    "metrics": 0, "crypto": 1, "payment_gateway": 4, "email_provider": 2,
    "sms_provider": 1, "storage_backend": 0, "merchants": 11,
    "customers": 3, "transactions": 10, "subscriptions": 4, "invoices": 4,
    "refunds": 3, "disputes": 0, "audit_log": 0, "api_merchants": 1,
    "api_transactions": 1, "api_subscriptions": 1, "api_webhooks": 2,
    "web_server": 0, "worker_service": 0, "cron_service": 0,
}

EXPECTED_EFFERENT = DIRECT_DEP_COUNTS  # same values

EXPECTED_INSTABILITY = {
    "config": 0.0, "crypto": 0.5, "logging": 0.0833, "http_client": 0.25,
    "database": 0.1667, "metrics": 1.0, "payment_gateway": 0.5,
    "email_provider": 0.6667, "sms_provider": 0.8, "storage_backend": 1.0,
    "merchants": 0.3125, "customers": 0.5714, "transactions": 0.375,
    "subscriptions": 0.6, "invoices": 0.6, "refunds": 0.625,
    "disputes": 1.0, "audit_log": 1.0, "api_merchants": 0.8,
    "api_transactions": 0.8333, "api_subscriptions": 0.8333,
    "api_webhooks": 0.7143, "web_server": 1.0, "worker_service": 1.0,
    "cron_service": 1.0,
}


# ── Helpers ─────────────────────────────────────────────────────


@pytest.fixture
def report():
    assert os.path.exists(REPORT_PATH), f"Report not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        data = json.load(f)
    return data


@pytest.fixture
def db():
    assert os.path.exists(DB_PATH), f"Database not found at {DB_PATH}"
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def _get_pkg(report, name):
    packages = report["packages"]
    if isinstance(packages, dict):
        return packages[name]
    for p in packages:
        if p.get("name") == name:
            return p
    raise KeyError(f"Package {name} not found in report")


def _get_field(obj, *candidates):
    for key in candidates:
        if key in obj:
            return obj[key]
    return None


def _has_cycle(adj, nodes):
    """Return True if the directed graph has a cycle (DFS-based)."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in nodes}

    def dfs(u):
        color[u] = GRAY
        for v in adj.get(u, []):
            if v not in nodes:
                continue
            if color[v] == GRAY:
                return True
            if color[v] == WHITE and dfs(v):
                return True
        color[u] = BLACK
        return False

    return any(color[n] == WHITE and dfs(n) for n in nodes)


# ── Report Structure Tests ──────────────────────────────────────


class TestReportStructure:
    def test_report_exists_and_valid_json(self, report):
        assert report is not None

    def test_has_packages_section(self, report):
        assert "packages" in report

    def test_has_summary_section(self, report):
        assert "summary" in report

    def test_has_feedback_arc_sets(self, report):
        assert "feedback_arc_sets" in report

    def test_all_25_packages_present(self, report):
        packages = report["packages"]
        if isinstance(packages, dict):
            pkg_names = set(packages.keys())
        else:
            pkg_names = {p["name"] for p in packages}
        assert len(pkg_names) == 25
        for name in LAYER_MAP:
            assert name in pkg_names, f"Missing package: {name}"

    def test_packages_have_transitive_dep_count(self, report):
        for name in LAYER_MAP:
            pkg = _get_pkg(report, name)
            assert "transitive_dep_count" in pkg, \
                f"{name} missing transitive_dep_count field"
            assert isinstance(pkg["transitive_dep_count"], int), \
                f"{name} transitive_dep_count should be int"

    def test_packages_have_coupling_fields(self, report):
        for name in LAYER_MAP:
            pkg = _get_pkg(report, name)
            assert "afferent_coupling" in pkg, \
                f"{name} missing afferent_coupling"
            assert "efferent_coupling" in pkg, \
                f"{name} missing efferent_coupling"
            assert "instability" in pkg, \
                f"{name} missing instability"


# ── Layer Assignment Tests ──────────────────────────────────────


class TestLayerAssignment:
    def test_layer_assignments(self, report):
        for name, expected_idx in LAYER_MAP.items():
            pkg = _get_pkg(report, name)
            layer = _get_field(pkg, "layer", "layer_name")
            layer_idx = _get_field(pkg, "layer_index")
            if layer_idx is not None:
                assert layer_idx == expected_idx, \
                    f"{name}: expected layer index {expected_idx}, got {layer_idx}"
            elif layer is not None:
                expected_name = LAYER_NAMES[expected_idx]
                assert layer == expected_name, \
                    f"{name}: expected layer '{expected_name}', got '{layer}'"
            else:
                pytest.fail(f"{name}: no layer or layer_index field found")


# ── Violation Detection Tests ───────────────────────────────────


class TestViolationDetection:
    def test_logging_has_layering_violation(self, report):
        pkg = _get_pkg(report, "logging")
        violations = pkg.get("violations", [])
        assert len(violations) > 0, "logging should have at least one violation"
        vtext = json.dumps(violations).lower()
        assert "merchants" in vtext or "merchant" in vtext

    def test_sms_provider_has_layering_violation(self, report):
        pkg = _get_pkg(report, "sms_provider")
        violations = pkg.get("violations", [])
        assert len(violations) > 0, "sms_provider should have at least one violation"
        vtext = json.dumps(violations).lower()
        assert "merchants" in vtext or "merchant" in vtext

    def test_subscriptions_has_cycle_violation(self, report):
        pkg = _get_pkg(report, "subscriptions")
        violations = pkg.get("violations", [])
        assert len(violations) > 0
        vtext = json.dumps(violations).lower()
        assert "cycle" in vtext or "invoices" in vtext

    def test_clean_packages_have_no_violations(self, report):
        for name in LAYER_MAP:
            if name not in PACKAGES_WITH_VIOLATIONS:
                pkg = _get_pkg(report, name)
                violations = pkg.get("violations", [])
                assert len(violations) == 0, \
                    f"{name} should have no violations but has: {violations}"

    def test_exactly_three_packages_with_violations(self, report):
        count = sum(
            1 for name in LAYER_MAP
            if len(_get_pkg(report, name).get("violations", [])) > 0
        )
        assert count == 3, f"Expected 3 packages with violations, got {count}"


# ── Cycle / SCC Tests ──────────────────────────────────────────


class TestCycleDetection:
    def test_subscriptions_invoices_cycle_detected(self, report):
        pkg = _get_pkg(report, "subscriptions")
        violations = pkg.get("violations", [])
        assert any(
            "invoices" in json.dumps(v).lower() or "cycle" in json.dumps(v).lower()
            for v in violations
        )

    def test_no_false_positive_cycles_layer0(self, report):
        for name in ["config", "crypto", "http_client", "database", "metrics"]:
            pkg = _get_pkg(report, name)
            violations = pkg.get("violations", [])
            cycle_v = [v for v in violations if "cycle" in json.dumps(v).lower()]
            assert len(cycle_v) == 0, f"{name} should have no cycle violations"

    def test_no_false_positive_cycles_layer1(self, report):
        for name in ["payment_gateway", "email_provider", "sms_provider",
                      "storage_backend"]:
            pkg = _get_pkg(report, name)
            violations = pkg.get("violations", [])
            cycle_v = [v for v in violations if "cycle" in json.dumps(v).lower()]
            assert len(cycle_v) == 0, f"{name} should have no cycle violations"

    def test_refunds_no_violations(self, report):
        pkg = _get_pkg(report, "refunds")
        assert len(pkg.get("violations", [])) == 0

    def test_crypto_no_violations(self, report):
        pkg = _get_pkg(report, "crypto")
        assert len(pkg.get("violations", [])) == 0

    def test_scc_count(self, report):
        s = report["summary"]
        scc_count = _get_field(s, "scc_count")
        assert scc_count is not None, "Missing scc_count in summary"
        assert scc_count == 2, f"Expected 2 SCCs with size>1, got {scc_count}"

    def test_largest_scc_size(self, report):
        s = report["summary"]
        largest = _get_field(s, "largest_scc_size")
        assert largest is not None, "Missing largest_scc_size in summary"
        assert largest == 6, f"Expected largest SCC size 6, got {largest}"


# ── Upgrade Analysis Tests ──────────────────────────────────────


class TestUpgradeAnalysis:
    def _is_upgradeable(self, report, name):
        pkg = _get_pkg(report, name)
        return bool(_get_field(pkg, "can_upgrade", "upgradeable"))

    def test_false_to_layered_upgrades(self, report):
        for name in ["http_client", "api_subscriptions", "web_server",
                      "worker_service", "cron_service"]:
            assert self._is_upgradeable(report, name), \
                f"{name} should be upgradeable (false -> layered)"

    def test_false_cannot_upgrade(self, report):
        for name in ["email_provider", "disputes"]:
            assert not self._is_upgradeable(report, name), \
                f"{name} should NOT be upgradeable"

    def test_layered_to_layered_dag_upgrades(self, report):
        for name in ["database", "metrics", "payment_gateway", "merchants",
                      "customers", "transactions", "audit_log",
                      "api_merchants", "api_transactions", "api_webhooks"]:
            assert self._is_upgradeable(report, name), \
                f"{name} should be upgradeable (layered -> layered_dag)"

    def test_layered_cannot_upgrade(self, report):
        for name in ["logging", "sms_provider", "invoices"]:
            assert not self._is_upgradeable(report, name), \
                f"{name} should NOT be upgradeable"

    def test_layered_dag_to_dag_upgrades(self, report):
        for name in ["config", "storage_backend"]:
            assert self._is_upgradeable(report, name), \
                f"{name} should be upgradeable (layered_dag -> dag)"

    def test_subscriptions_cannot_upgrade(self, report):
        assert not self._is_upgradeable(report, "subscriptions")

    def test_dag_packages_already_at_max(self, report):
        for name in ["crypto", "refunds"]:
            assert not self._is_upgradeable(report, name)

    def test_total_upgradeable_count(self, report):
        count = sum(
            1 for name in LAYER_MAP
            if self._is_upgradeable(report, name)
        )
        assert count == 17, f"Expected 17 upgradeable, got {count}"


# ── Summary Statistics Tests ────────────────────────────────────


class TestSummaryStatistics:
    def test_total_packages(self, report):
        s = report["summary"]
        total = _get_field(s, "total_packages", "total")
        assert total == 25

    def test_level_distribution(self, report):
        s = report["summary"]
        by_level = _get_field(s, "by_level", "distribution")
        assert by_level is not None
        assert by_level.get("false", 0) == 7
        assert by_level.get("layered", 0) == 13
        assert by_level.get("layered_dag", 0) == 3
        assert by_level.get("dag", 0) == 2

    def test_violations_count(self, report):
        s = report["summary"]
        v = _get_field(s, "violations_count", "total_violations", "violations")
        assert v == 3

    def test_upgradeable_count(self, report):
        s = report["summary"]
        u = _get_field(s, "upgradeable_count", "total_upgradeable", "upgradeable")
        assert u == 17


# ── Transitive Dependency Tests ─────────────────────────────────


class TestTransitiveDeps:
    def test_config_zero_transitive_deps(self, report):
        pkg = _get_pkg(report, "config")
        assert pkg["transitive_dep_count"] == 0

    def test_crypto_one_transitive_dep(self, report):
        pkg = _get_pkg(report, "crypto")
        assert pkg["transitive_dep_count"] == 1

    def test_logging_transitive_deps(self, report):
        pkg = _get_pkg(report, "logging")
        assert pkg["transitive_dep_count"] == 7, \
            f"logging: expected 7 transitive deps, got {pkg['transitive_dep_count']}"

    def test_web_server_max_transitive_deps(self, report):
        pkg = _get_pkg(report, "web_server")
        assert pkg["transitive_dep_count"] == 17, \
            f"web_server: expected 17 transitive deps, got {pkg['transitive_dep_count']}"

    def test_transactions_transitive_deps(self, report):
        pkg = _get_pkg(report, "transactions")
        assert pkg["transitive_dep_count"] == 9

    def test_subscriptions_transitive_deps(self, report):
        pkg = _get_pkg(report, "subscriptions")
        assert pkg["transitive_dep_count"] == 11

    def test_disputes_transitive_deps(self, report):
        pkg = _get_pkg(report, "disputes")
        assert pkg["transitive_dep_count"] == 12

    def test_worker_service_transitive_deps(self, report):
        pkg = _get_pkg(report, "worker_service")
        assert pkg["transitive_dep_count"] == 14

    def test_all_transitive_dep_counts(self, report):
        """Verify every package's transitive dep count matches ground truth."""
        for name, expected in EXPECTED_TRANSITIVE_COUNTS.items():
            pkg = _get_pkg(report, name)
            actual = pkg["transitive_dep_count"]
            assert actual == expected, \
                f"{name}: expected {expected} transitive deps, got {actual}"


# ── Coupling Metrics Tests ──────────────────────────────────────


class TestCouplingMetrics:
    def test_config_coupling(self, report):
        pkg = _get_pkg(report, "config")
        assert pkg["afferent_coupling"] == 24
        assert pkg["efferent_coupling"] == 0
        assert abs(pkg["instability"] - 0.0) < 0.001

    def test_logging_coupling(self, report):
        pkg = _get_pkg(report, "logging")
        assert pkg["afferent_coupling"] == 22
        assert pkg["efferent_coupling"] == 2
        assert abs(pkg["instability"] - 0.0833) < 0.001

    def test_merchants_coupling(self, report):
        pkg = _get_pkg(report, "merchants")
        assert pkg["afferent_coupling"] == 11
        assert pkg["efferent_coupling"] == 5
        assert abs(pkg["instability"] - 0.3125) < 0.001

    def test_web_server_coupling(self, report):
        pkg = _get_pkg(report, "web_server")
        assert pkg["afferent_coupling"] == 0
        assert pkg["efferent_coupling"] == 7
        assert abs(pkg["instability"] - 1.0) < 0.001

    def test_metrics_coupling(self, report):
        """metrics is a leaf — nobody imports it, instability should be 1.0."""
        pkg = _get_pkg(report, "metrics")
        assert pkg["afferent_coupling"] == 0
        assert pkg["efferent_coupling"] == 2
        assert abs(pkg["instability"] - 1.0) < 0.001

    def test_disputes_coupling(self, report):
        pkg = _get_pkg(report, "disputes")
        assert pkg["afferent_coupling"] == 0
        assert pkg["efferent_coupling"] == 8
        assert abs(pkg["instability"] - 1.0) < 0.001

    def test_transactions_coupling(self, report):
        pkg = _get_pkg(report, "transactions")
        assert pkg["afferent_coupling"] == 10
        assert pkg["efferent_coupling"] == 6
        assert abs(pkg["instability"] - 0.375) < 0.001

    def test_all_afferent_coupling(self, report):
        for name, expected in EXPECTED_AFFERENT.items():
            pkg = _get_pkg(report, name)
            assert pkg["afferent_coupling"] == expected, \
                f"{name}: expected Ca={expected}, got {pkg['afferent_coupling']}"

    def test_all_efferent_coupling(self, report):
        for name, expected in EXPECTED_EFFERENT.items():
            pkg = _get_pkg(report, name)
            assert pkg["efferent_coupling"] == expected, \
                f"{name}: expected Ce={expected}, got {pkg['efferent_coupling']}"

    def test_all_instability(self, report):
        for name, expected in EXPECTED_INSTABILITY.items():
            pkg = _get_pkg(report, name)
            assert abs(pkg["instability"] - expected) < 0.001, \
                f"{name}: expected I={expected}, got {pkg['instability']}"

    def test_stable_packages_low_instability(self, report):
        """Config and logging should be the most stable (lowest instability)."""
        config_i = _get_pkg(report, "config")["instability"]
        logging_i = _get_pkg(report, "logging")["instability"]
        assert config_i < 0.01, "config should have instability near 0"
        assert logging_i < 0.1, "logging should have low instability"

    def test_leaf_services_max_instability(self, report):
        """Services with no dependents should have instability 1.0."""
        for name in ["web_server", "worker_service", "cron_service"]:
            pkg = _get_pkg(report, name)
            assert abs(pkg["instability"] - 1.0) < 0.001, \
                f"{name} should have instability 1.0"


# ── Feedback Arc Set Tests ──────────────────────────────────────


class TestFeedbackArcSets:
    def test_fas_has_two_entries(self, report):
        fas = report["feedback_arc_sets"]
        assert len(fas) == 2, f"Expected 2 FAS entries (2 SCCs), got {len(fas)}"

    def test_fas_entries_sorted_by_first_member(self, report):
        fas = report["feedback_arc_sets"]
        first_members = [f["members"][0] for f in fas]
        assert first_members == sorted(first_members), \
            "FAS entries must be sorted by first member name"

    def test_fas_large_scc_members(self, report):
        fas = report["feedback_arc_sets"]
        large_fas = [f for f in fas if len(f["members"]) == 6]
        assert len(large_fas) == 1, "Expected one FAS entry with 6 members"
        assert set(large_fas[0]["members"]) == LARGE_SCC_MEMBERS

    def test_fas_small_scc_members(self, report):
        fas = report["feedback_arc_sets"]
        small_fas = [f for f in fas if len(f["members"]) == 2]
        assert len(small_fas) == 1, "Expected one FAS entry with 2 members"
        assert set(small_fas[0]["members"]) == SMALL_SCC_MEMBERS

    def test_fas_large_scc_edge_count(self, report):
        """Minimum FAS for the 6-node SCC requires exactly 2 edges."""
        fas = report["feedback_arc_sets"]
        large_fas = [f for f in fas if len(f["members"]) == 6][0]
        edges = large_fas["edges_to_remove"]
        assert len(edges) == 2, \
            f"Expected 2 edges in FAS for 6-node SCC, got {len(edges)}"

    def test_fas_small_scc_edge_count(self, report):
        """Minimum FAS for the 2-node SCC requires exactly 1 edge."""
        fas = report["feedback_arc_sets"]
        small_fas = [f for f in fas if len(f["members"]) == 2][0]
        edges = small_fas["edges_to_remove"]
        assert len(edges) == 1, \
            f"Expected 1 edge in FAS for 2-node SCC, got {len(edges)}"

    def test_fas_large_scc_edges_are_valid(self, report):
        """All FAS edges must be actual edges within the SCC."""
        fas = report["feedback_arc_sets"]
        large_fas = [f for f in fas if len(f["members"]) == 6][0]
        for edge in large_fas["edges_to_remove"]:
            s, t = edge[0], edge[1]
            assert (s, t) in LARGE_SCC_EDGES, \
                f"FAS edge ({s}, {t}) is not an edge in the 6-node SCC"

    def test_fas_small_scc_edges_are_valid(self, report):
        fas = report["feedback_arc_sets"]
        small_fas = [f for f in fas if len(f["members"]) == 2][0]
        for edge in small_fas["edges_to_remove"]:
            s, t = edge[0], edge[1]
            assert (s, t) in SMALL_SCC_EDGES, \
                f"FAS edge ({s}, {t}) is not an edge in the 2-node SCC"

    def test_fas_large_scc_breaks_cycles(self, report):
        """Removing FAS edges from the 6-node SCC must make it acyclic."""
        fas = report["feedback_arc_sets"]
        large_fas = [f for f in fas if len(f["members"]) == 6][0]
        members = set(large_fas["members"])
        edges_to_remove = {(e[0], e[1]) for e in large_fas["edges_to_remove"]}

        # Build adjacency list for SCC subgraph, minus FAS edges
        adj = defaultdict(list)
        for s, t in LARGE_SCC_EDGES:
            if (s, t) not in edges_to_remove:
                adj[s].append(t)

        assert not _has_cycle(adj, members), \
            "Removing FAS edges should make the 6-node SCC acyclic"

    def test_fas_small_scc_breaks_cycles(self, report):
        """Removing FAS edges from the 2-node SCC must make it acyclic."""
        fas = report["feedback_arc_sets"]
        small_fas = [f for f in fas if len(f["members"]) == 2][0]
        members = set(small_fas["members"])
        edges_to_remove = {(e[0], e[1]) for e in small_fas["edges_to_remove"]}

        adj = defaultdict(list)
        for s, t in SMALL_SCC_EDGES:
            if (s, t) not in edges_to_remove:
                adj[s].append(t)

        assert not _has_cycle(adj, members), \
            "Removing FAS edge should make the 2-node SCC acyclic"

    def test_fas_members_sorted(self, report):
        """Members list within each FAS entry must be sorted."""
        for fas_entry in report["feedback_arc_sets"]:
            members = fas_entry["members"]
            assert members == sorted(members), \
                f"Members must be sorted, got {members}"


# ── SQLite Database Tests ───────────────────────────────────────


class TestSQLiteDatabase:
    def test_database_exists(self):
        assert os.path.exists(DB_PATH), f"Database not found at {DB_PATH}"

    def test_packages_table_schema(self, db):
        cur = db.execute("PRAGMA table_info(packages)")
        cols = {row["name"]: row["type"].upper() for row in cur.fetchall()}
        assert "name" in cols, "packages table missing 'name' column"
        assert "layer" in cols, "packages table missing 'layer' column"
        assert "layer_index" in cols, "packages table missing 'layer_index' column"
        assert "strict_dependencies" in cols, \
            "packages table missing 'strict_dependencies' column"

    def test_dependencies_table_schema(self, db):
        cur = db.execute("PRAGMA table_info(dependencies)")
        cols = {row["name"] for row in cur.fetchall()}
        assert "source" in cols
        assert "target" in cols

    def test_transitive_deps_table_schema(self, db):
        cur = db.execute("PRAGMA table_info(transitive_deps)")
        cols = {row["name"] for row in cur.fetchall()}
        assert "source" in cols
        assert "target" in cols
        assert "distance" in cols

    def test_violations_table_schema(self, db):
        cur = db.execute("PRAGMA table_info(violations)")
        cols = {row["name"] for row in cur.fetchall()}
        assert "package" in cols
        assert "violation_type" in cols
        assert "description" in cols

    def test_coupling_metrics_table_schema(self, db):
        cur = db.execute("PRAGMA table_info(coupling_metrics)")
        cols = {row["name"]: row["type"].upper() for row in cur.fetchall()}
        assert "name" in cols, "coupling_metrics missing 'name'"
        assert "afferent_coupling" in cols, "coupling_metrics missing 'afferent_coupling'"
        assert "efferent_coupling" in cols, "coupling_metrics missing 'efferent_coupling'"
        assert "instability" in cols, "coupling_metrics missing 'instability'"

    def test_packages_row_count(self, db):
        cur = db.execute("SELECT COUNT(*) AS c FROM packages")
        assert cur.fetchone()["c"] == 25

    def test_dependencies_row_count(self, db):
        cur = db.execute("SELECT COUNT(*) AS c FROM dependencies")
        count = cur.fetchone()["c"]
        assert count == TOTAL_DIRECT_EDGES, \
            f"Expected {TOTAL_DIRECT_EDGES} dependency edges, got {count}"

    def test_transitive_deps_row_count(self, db):
        cur = db.execute("SELECT COUNT(*) AS c FROM transitive_deps")
        count = cur.fetchone()["c"]
        assert count == TOTAL_TRANSITIVE_ROWS, \
            f"Expected {TOTAL_TRANSITIVE_ROWS} transitive rows, got {count}"

    def test_violations_row_count(self, db):
        cur = db.execute("SELECT COUNT(*) AS c FROM violations")
        assert cur.fetchone()["c"] == 3

    def test_coupling_metrics_row_count(self, db):
        cur = db.execute("SELECT COUNT(*) AS c FROM coupling_metrics")
        assert cur.fetchone()["c"] == 25

    def test_packages_data_correctness(self, db):
        for name, expected_idx in LAYER_MAP.items():
            cur = db.execute(
                "SELECT layer, layer_index, strict_dependencies FROM packages "
                "WHERE name = ?", (name,))
            row = cur.fetchone()
            assert row is not None, f"Package {name} not found in database"
            assert row["layer_index"] == expected_idx, \
                f"{name}: expected layer_index {expected_idx}, got {row['layer_index']}"
            assert row["strict_dependencies"] == EXPECTED_LEVELS[name]

    def test_direct_dep_counts_per_package(self, db):
        for name, expected in DIRECT_DEP_COUNTS.items():
            cur = db.execute(
                "SELECT COUNT(*) AS c FROM dependencies WHERE source = ?",
                (name,))
            actual = cur.fetchone()["c"]
            assert actual == expected, \
                f"{name}: expected {expected} direct deps, got {actual}"

    def test_transitive_distance_logging_config(self, db):
        cur = db.execute(
            "SELECT distance FROM transitive_deps "
            "WHERE source = 'logging' AND target = 'config'")
        row = cur.fetchone()
        assert row is not None, "Missing transitive edge logging->config"
        assert row["distance"] == 1

    def test_transitive_distance_logging_database(self, db):
        cur = db.execute(
            "SELECT distance FROM transitive_deps "
            "WHERE source = 'logging' AND target = 'database'")
        row = cur.fetchone()
        assert row is not None, "Missing transitive edge logging->database"
        assert row["distance"] == 2

    def test_transitive_distance_logging_crypto(self, db):
        cur = db.execute(
            "SELECT distance FROM transitive_deps "
            "WHERE source = 'logging' AND target = 'crypto'")
        row = cur.fetchone()
        assert row is not None, "Missing transitive edge logging->crypto"
        assert row["distance"] == 3

    def test_transitive_distance_web_server_crypto(self, db):
        cur = db.execute(
            "SELECT distance FROM transitive_deps "
            "WHERE source = 'web_server' AND target = 'crypto'")
        row = cur.fetchone()
        assert row is not None, "Missing transitive edge web_server->crypto"
        assert row["distance"] == 4

    def test_config_has_no_transitive_deps(self, db):
        cur = db.execute(
            "SELECT COUNT(*) AS c FROM transitive_deps WHERE source = 'config'")
        assert cur.fetchone()["c"] == 0

    def test_transitive_count_per_source(self, db):
        for name in ["config", "crypto", "logging", "web_server", "transactions"]:
            cur = db.execute(
                "SELECT COUNT(*) AS c FROM transitive_deps WHERE source = ?",
                (name,))
            actual = cur.fetchone()["c"]
            expected = EXPECTED_TRANSITIVE_COUNTS[name]
            assert actual == expected, \
                f"{name}: expected {expected} transitive rows, got {actual}"

    def test_scc_mutual_reachability(self, db):
        """All members of the 6-node SCC should mutually reach each other."""
        members = sorted(LARGE_SCC_MEMBERS)
        for src in members:
            for tgt in members:
                if src == tgt:
                    continue
                cur = db.execute(
                    "SELECT distance FROM transitive_deps "
                    "WHERE source = ? AND target = ?", (src, tgt))
                row = cur.fetchone()
                assert row is not None, \
                    f"SCC members {src} and {tgt} should be mutually reachable"
                assert row["distance"] > 0

    def test_coupling_metrics_config(self, db):
        cur = db.execute(
            "SELECT afferent_coupling, efferent_coupling, instability "
            "FROM coupling_metrics WHERE name = 'config'")
        row = cur.fetchone()
        assert row is not None
        assert row["afferent_coupling"] == 24
        assert row["efferent_coupling"] == 0
        assert abs(row["instability"] - 0.0) < 0.001

    def test_coupling_metrics_merchants(self, db):
        cur = db.execute(
            "SELECT afferent_coupling, efferent_coupling, instability "
            "FROM coupling_metrics WHERE name = 'merchants'")
        row = cur.fetchone()
        assert row is not None
        assert row["afferent_coupling"] == 11
        assert row["efferent_coupling"] == 5
        assert abs(row["instability"] - 0.3125) < 0.001

    def test_coupling_metrics_web_server(self, db):
        cur = db.execute(
            "SELECT afferent_coupling, efferent_coupling, instability "
            "FROM coupling_metrics WHERE name = 'web_server'")
        row = cur.fetchone()
        assert row is not None
        assert row["afferent_coupling"] == 0
        assert row["efferent_coupling"] == 7
        assert abs(row["instability"] - 1.0) < 0.001

    def test_coupling_metrics_all_afferent(self, db):
        """Verify afferent coupling in DB matches ground truth for all packages."""
        for name, expected in EXPECTED_AFFERENT.items():
            cur = db.execute(
                "SELECT afferent_coupling FROM coupling_metrics WHERE name = ?",
                (name,))
            row = cur.fetchone()
            assert row is not None, f"Missing coupling_metrics row for {name}"
            assert row["afferent_coupling"] == expected, \
                f"{name}: expected Ca={expected}, got {row['afferent_coupling']}"


# ── Graph Visualization Tests ───────────────────────────────────


class TestGraphVisualization:
    def test_svg_file_exists(self):
        assert os.path.exists(SVG_PATH), f"SVG not found at {SVG_PATH}"

    def test_svg_has_content(self):
        size = os.path.getsize(SVG_PATH)
        assert size > 1000, f"SVG file too small ({size} bytes)"

    def test_svg_is_valid_xml(self):
        tree = ET.parse(SVG_PATH)
        root = tree.getroot()
        tag = root.tag
        assert "svg" in tag.lower(), f"Root element is '{tag}', expected svg"

    def test_svg_contains_package_names(self):
        with open(SVG_PATH) as f:
            content = f.read()
        for name in LAYER_MAP:
            assert name in content, \
                f"SVG should contain package name '{name}'"

    def test_svg_contains_layer_labels(self):
        with open(SVG_PATH) as f:
            content = f.read()
        for layer_name in LAYER_NAMES.values():
            assert layer_name in content, \
                f"SVG should contain layer label '{layer_name}'"

    def test_svg_contains_red_edges(self):
        """There should be red-colored elements for violation edges."""
        with open(SVG_PATH) as f:
            content = f.read()
        assert "red" in content.lower() or "#ff0000" in content.lower(), \
            "SVG should contain red-colored edges for violations"

    def test_svg_contains_node_colors(self):
        """Check that ratchet-level node colors appear in the SVG."""
        with open(SVG_PATH) as f:
            content = f.read().lower()
        assert "#add8e6" in content, \
            "SVG should contain #ADD8E6 (layered node color)"
