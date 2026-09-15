"""
Tests for the dependency ratchet audit and migration analysis.

"""
import csv
import json
import os
import sqlite3
import pytest


LAYER_ORDER = {"utility": 0, "power": 1, "business": 2, "api": 3, "services": 4}
LEVEL_NAMES = ["false", "layered", "layered_dag", "dag"]

# The 4 undeclared runtime dependencies that must be discovered
EXPECTED_UNDECLARED = {
    ("analytics_model", "admin_api"),
    ("config", "metrics"),
    ("search_client", "cache"),
    ("shipping_model", "payment_api"),
}


@pytest.fixture(scope="session")
def packages():
    """Load package data from SQLite and merge known undeclared runtime deps."""
    conn = sqlite3.connect("/app/monolith.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    pkgs = {}
    cur.execute("""
        SELECT p.name, l.name as layer, l.rank as layer_rank, p.enforcement_level
        FROM packages p JOIN layers l ON p.layer_id = l.id
    """)
    for row in cur.fetchall():
        cur2 = conn.cursor()
        cur2.execute("SELECT target FROM dependencies WHERE source = ?", (row["name"],))
        deps = [r[0] for r in cur2.fetchall()]
        pkgs[row["name"]] = {
            "name": row["name"],
            "layer": row["layer"],
            "layer_rank": row["layer_rank"],
            "strict_dependencies": row["enforcement_level"],
            "dependencies": deps,
        }
    conn.close()
    # Merge runtime deps to get complete graph
    for src, tgt in EXPECTED_UNDECLARED:
        if tgt not in pkgs[src]["dependencies"]:
            pkgs[src]["dependencies"].append(tgt)
    return pkgs


@pytest.fixture(scope="session")
def report():
    report_path = "/app/output/report.json"
    assert os.path.exists(report_path), "report.json must exist at /app/output/report.json"
    with open(report_path) as f:
        return json.load(f)


# ============================================================
# Section 1: Report structure
# ============================================================


class TestReportStructure:
    def test_report_has_all_keys(self, report):
        required = {"audit", "violations", "promotable", "cycles", "critical_edges", "migration_plan"}
        assert required.issubset(set(report.keys())), f"Missing keys: {required - set(report.keys())}"

    def test_audit_has_subkeys(self, report):
        assert "undeclared_dependencies" in report["audit"]
        assert "invalid_levels" in report["audit"]

    def test_violations_format(self, report):
        for v in report["violations"]:
            assert "package" in v
            assert "dependency" in v
            assert "rule" in v
            assert v["rule"] in ("layered", "layered_dag", "dag")
            assert "reason" in v

    def test_promotable_format(self, report):
        for p in report["promotable"]:
            assert "package" in p
            assert "current" in p
            assert "promoted_to" in p
            levels = LEVEL_NAMES
            assert levels.index(p["promoted_to"]) > levels.index(p["current"])

    def test_cycles_format(self, report):
        for scc in report["cycles"]:
            assert isinstance(scc, list)
            assert len(scc) >= 2
            assert scc == sorted(scc), f"SCC must be sorted: {scc}"

    def test_migration_plan_format(self, report):
        for s in report["migration_plan"]:
            assert "step" in s
            assert "package" in s
            assert "from" in s
            assert "to" in s


# ============================================================
# Section 2: Audit — undeclared dependencies
# ============================================================


class TestUndeclaredDependencies:
    def test_undeclared_count(self, report):
        assert len(report["audit"]["undeclared_dependencies"]) == 4, (
            f"Expected 4 undeclared deps, got {len(report['audit']['undeclared_dependencies'])}"
        )

    def test_undeclared_identities(self, report):
        found = {(d["source"], d["target"]) for d in report["audit"]["undeclared_dependencies"]}
        assert found == EXPECTED_UNDECLARED, (
            f"Undeclared deps mismatch.\n  Expected: {EXPECTED_UNDECLARED}\n  Got: {found}"
        )

    def test_undeclared_have_evidence(self, report):
        for d in report["audit"]["undeclared_dependencies"]:
            assert "evidence" in d and len(d["evidence"]) > 0, (
                f"Undeclared dep {d['source']}->{d['target']} missing evidence"
            )

    def test_undeclared_sorted(self, report):
        deps = report["audit"]["undeclared_dependencies"]
        keys = [(d["source"], d["target"]) for d in deps]
        assert keys == sorted(keys), "Undeclared deps must be sorted by (source, target)"


# ============================================================
# Section 3: Audit — invalid levels
# ============================================================


class TestInvalidLevels:
    def test_invalid_count(self, report):
        assert len(report["audit"]["invalid_levels"]) == 5, (
            f"Expected 5 invalid levels, got {len(report['audit']['invalid_levels'])}"
        )

    def test_db_driver_invalid(self, report):
        """db_driver at layered_dag has same-layer cycle with storage_client."""
        matches = [e for e in report["audit"]["invalid_levels"] if e["package"] == "db_driver"]
        assert len(matches) == 1
        assert matches[0]["current_level"] == "layered_dag"
        assert matches[0]["max_valid_level"] == "layered"

    def test_queue_client_invalid(self, report):
        """queue_client at layered depends on user_model in higher layer."""
        matches = [e for e in report["audit"]["invalid_levels"] if e["package"] == "queue_client"]
        assert len(matches) == 1
        assert matches[0]["current_level"] == "layered"
        assert matches[0]["max_valid_level"] == "false"

    def test_payment_model_invalid(self, report):
        """payment_model at layered depends on auth_api in higher layer."""
        matches = [e for e in report["audit"]["invalid_levels"] if e["package"] == "payment_model"]
        assert len(matches) == 1
        assert matches[0]["current_level"] == "layered"
        assert matches[0]["max_valid_level"] == "false"

    def test_analytics_model_invalid(self, report):
        """analytics_model at layered depends on admin_api (higher layer) via runtime dep."""
        matches = [e for e in report["audit"]["invalid_levels"] if e["package"] == "analytics_model"]
        assert len(matches) == 1
        assert matches[0]["current_level"] == "layered"
        assert matches[0]["max_valid_level"] == "false"

    def test_order_api_invalid(self, report):
        """order_api at layered_dag — reachable same-layer subgraph has auth_api<->payment_api cycle."""
        matches = [e for e in report["audit"]["invalid_levels"] if e["package"] == "order_api"]
        assert len(matches) == 1
        assert matches[0]["current_level"] == "layered_dag"
        assert matches[0]["max_valid_level"] == "layered"

    def test_invalid_sorted(self, report):
        names = [e["package"] for e in report["audit"]["invalid_levels"]]
        assert names == sorted(names), "Invalid levels must be sorted by package name"


# ============================================================
# Section 4: Violations
# ============================================================


class TestViolations:
    def test_violation_count(self, report):
        assert len(report["violations"]) == 5, (
            f"Expected 5 violations, got {len(report['violations'])}"
        )

    def test_analytics_model_violation(self, report):
        """analytics_model (business, layered) depends on admin_api (api) via runtime dep."""
        viols = [v for v in report["violations"] if v["package"] == "analytics_model"]
        assert len(viols) == 1
        assert viols[0]["dependency"] == "admin_api"
        assert viols[0]["rule"] == "layered"

    def test_db_driver_violation(self, report):
        """db_driver (power, layered_dag) has same-layer cycle via storage_client."""
        viols = [v for v in report["violations"] if v["package"] == "db_driver"]
        assert len(viols) == 1
        assert viols[0]["dependency"] == "storage_client"
        assert viols[0]["rule"] == "layered_dag"

    def test_order_api_violation(self, report):
        """order_api (api, layered_dag) reachable same-layer subgraph has cycle."""
        viols = [v for v in report["violations"] if v["package"] == "order_api"]
        assert len(viols) == 1
        assert viols[0]["dependency"] == "auth_api"
        assert viols[0]["rule"] == "layered_dag"

    def test_payment_model_violation(self, report):
        """payment_model (business, layered) depends on auth_api (api)."""
        viols = [v for v in report["violations"] if v["package"] == "payment_model"]
        assert len(viols) == 1
        assert viols[0]["dependency"] == "auth_api"
        assert viols[0]["rule"] == "layered"

    def test_queue_client_violation(self, report):
        """queue_client (power, layered) depends on user_model (business)."""
        viols = [v for v in report["violations"] if v["package"] == "queue_client"]
        assert len(viols) == 1
        assert viols[0]["dependency"] == "user_model"
        assert viols[0]["rule"] == "layered"

    def test_no_false_package_violations(self, report, packages):
        """Packages at level 'false' should never have violations reported."""
        false_pkgs = {n for n, p in packages.items() if p["strict_dependencies"] == "false"}
        violating_pkgs = {v["package"] for v in report["violations"]}
        assert not (violating_pkgs & false_pkgs), (
            f"Packages at 'false' should have no violations: {violating_pkgs & false_pkgs}"
        )


# ============================================================
# Section 5: Cycle detection (SCCs on complete graph)
# ============================================================


class TestCycles:
    def test_cycle_count(self, report):
        assert len(report["cycles"]) == 2, f"Expected 2 SCCs, got {len(report['cycles'])}"

    def test_small_scc(self, report):
        """db_driver <-> storage_client cycle in power layer."""
        small_sccs = [s for s in report["cycles"] if len(s) == 2]
        assert len(small_sccs) == 1
        assert small_sccs[0] == ["db_driver", "storage_client"]

    def test_large_scc_membership(self, report):
        """Large cycle must include admin_api (pulled in via runtime dep analytics_model->admin_api)."""
        large_sccs = [s for s in report["cycles"] if len(s) > 2]
        assert len(large_sccs) == 1
        scc = large_sccs[0]
        expected_members = {
            "admin_api",
            "analytics_model",
            "auth_api",
            "fraud_model",
            "inventory_model",
            "notification_model",
            "order_model",
            "payment_api",
            "payment_model",
        }
        assert expected_members == set(scc), (
            f"Large SCC membership mismatch.\n"
            f"  Expected: {sorted(expected_members)}\n"
            f"  Got: {sorted(scc)}\n"
            f"  Missing: {sorted(expected_members - set(scc))}\n"
            f"  Extra: {sorted(set(scc) - expected_members)}"
        )

    def test_large_scc_size(self, report):
        large_sccs = [s for s in report["cycles"] if len(s) > 2]
        assert len(large_sccs[0]) == 9, (
            f"Large SCC should have 9 members, got {len(large_sccs[0])}"
        )

    def test_no_singleton_sccs(self, report):
        for scc in report["cycles"]:
            assert len(scc) >= 2


# ============================================================
# Section 6: Critical edges (feedback arc set)
# ============================================================


class TestCriticalEdges:
    def test_critical_edge_minimum_count(self, report):
        """Need at least one edge per SCC to break all cycles."""
        assert len(report["critical_edges"]) >= 2, (
            f"Need at least 2 critical edges, got {len(report['critical_edges'])}"
        )

    def test_critical_edges_sorted(self, report):
        edges = report["critical_edges"]
        keys = [(e["source"], e["target"]) for e in edges]
        assert keys == sorted(keys), "Critical edges must be sorted by (source, target)"

    def test_critical_edges_are_real_edges(self, report, packages):
        """Every critical edge must be an actual dependency in the complete graph."""
        for e in report["critical_edges"]:
            deps = packages[e["source"]]["dependencies"]
            assert e["target"] in deps, (
                f"Critical edge {e['source']}->{e['target']} is not an actual dependency"
            )

    def test_removing_critical_edges_breaks_all_cycles(self, report, packages):
        """After removing critical edges, the complete graph should be acyclic."""
        removed = {(e["source"], e["target"]) for e in report["critical_edges"]}

        adj = {}
        for name, pkg in packages.items():
            adj[name] = [d for d in pkg["dependencies"] if (name, d) not in removed]

        WHITE, GRAY, BLACK = 0, 1, 2
        color = {n: WHITE for n in packages}

        def has_cycle_from(node):
            color[node] = GRAY
            for dep in adj.get(node, []):
                if color[dep] == GRAY:
                    return True
                if color[dep] == WHITE and has_cycle_from(dep):
                    return True
            color[node] = BLACK
            return False

        for node in packages:
            if color[node] == WHITE:
                assert not has_cycle_from(node), (
                    f"Graph still has cycle after removing critical edges (at {node})"
                )

    def test_db_storage_cycle_broken(self, report):
        """At least one edge of db_driver<->storage_client must be in critical edges."""
        critical_set = {(e["source"], e["target"]) for e in report["critical_edges"]}
        has_ds = ("db_driver", "storage_client") in critical_set
        has_sd = ("storage_client", "db_driver") in critical_set
        assert has_ds or has_sd, "Must break db_driver<->storage_client cycle"

    def test_critical_edges_come_from_cycles(self, report):
        """Every critical edge should involve nodes from a cycle."""
        cycle_members = set()
        for scc in report["cycles"]:
            cycle_members.update(scc)
        for e in report["critical_edges"]:
            assert e["source"] in cycle_members and e["target"] in cycle_members, (
                f"Critical edge {e['source']}->{e['target']} involves non-cycle members"
            )

    def test_critical_edges_reasonable_count(self, report, packages):
        """Critical edges should not be excessive."""
        cycle_members = set()
        for scc in report["cycles"]:
            cycle_members.update(scc)
        total_scc_edges = sum(
            1
            for name in cycle_members
            for dep in packages[name]["dependencies"]
            if dep in cycle_members
        )
        assert len(report["critical_edges"]) <= total_scc_edges, (
            f"Too many critical edges ({len(report['critical_edges'])}) "
            f"vs SCC internal edges ({total_scc_edges})"
        )


# ============================================================
# Section 7: Promotability (from corrected levels)
# ============================================================


class TestPromotable:
    def test_promotable_count(self, report):
        assert len(report["promotable"]) == 25, (
            f"Expected 25 promotable packages, got {len(report['promotable'])}"
        )

    def test_no_already_dag_packages(self, report):
        """Packages already at 'dag' in corrected state should not be promotable."""
        for p in report["promotable"]:
            assert p["current"] != "dag"

    def test_db_driver_not_promotable(self, report):
        """db_driver is stuck at layered (same-layer cycle prevents layered_dag)."""
        matches = [p for p in report["promotable"] if p["package"] == "db_driver"]
        assert len(matches) == 0, "db_driver should not be promotable (stuck at layered)"

    def test_queue_client_not_promotable(self, report):
        """queue_client is stuck at false (upward dep)."""
        matches = [p for p in report["promotable"] if p["package"] == "queue_client"]
        assert len(matches) == 0, "queue_client should not be promotable (upward dep)"

    def test_analytics_model_not_promotable(self, report):
        """analytics_model stuck at false (runtime dep creates upward violation)."""
        matches = [p for p in report["promotable"] if p["package"] == "analytics_model"]
        assert len(matches) == 0, "analytics_model should not be promotable"

    def test_shipping_model_not_promotable(self, report):
        """shipping_model stuck at false (runtime dep creates upward violation)."""
        matches = [p for p in report["promotable"] if p["package"] == "shipping_model"]
        assert len(matches) == 0, "shipping_model should not be promotable"

    def test_user_model_promotable_to_layered_dag(self, report):
        """user_model has no same-layer business deps, can reach layered_dag."""
        matches = [p for p in report["promotable"] if p["package"] == "user_model"]
        assert len(matches) == 1
        assert matches[0]["current"] == "layered"
        assert matches[0]["promoted_to"] == "layered_dag"

    def test_utility_packages_reach_dag(self, report):
        """Non-dag utility packages should all be promotable to dag."""
        utility_promotable = [
            p for p in report["promotable"]
            if p["package"] in ("config", "crypto", "cache", "serializer", "metrics")
        ]
        for p in utility_promotable:
            assert p["promoted_to"] == "dag", (
                f"Utility package {p['package']} should reach dag, got {p['promoted_to']}"
            )

    def test_services_reach_layered_dag(self, report):
        """Service-layer packages should be promotable to layered_dag."""
        service_names = {"web_service", "worker_service", "admin_service", "cron_service", "webhook_service"}
        service_promotable = [p for p in report["promotable"] if p["package"] in service_names]
        assert len(service_promotable) == 5, f"All 5 services should be promotable"
        for p in service_promotable:
            assert p["promoted_to"] == "layered_dag", (
                f"Service {p['package']} should reach layered_dag, got {p['promoted_to']}"
            )

    def test_webhook_api_reaches_layered_dag(self, report):
        """webhook_api has no same-layer api deps, should reach layered_dag."""
        matches = [p for p in report["promotable"] if p["package"] == "webhook_api"]
        assert len(matches) == 1
        assert matches[0]["promoted_to"] == "layered_dag"

    def test_current_level_is_corrected(self, report):
        """The 'current' field must reflect corrected (post-rollback) levels."""
        corrected_map = {
            "db_driver": "layered",
            "queue_client": "false",
            "payment_model": "false",
            "analytics_model": "false",
            "order_api": "layered",
        }
        for p in report["promotable"]:
            if p["package"] in corrected_map:
                assert p["current"] == corrected_map[p["package"]], (
                    f"{p['package']}: current should be corrected to "
                    f"{corrected_map[p['package']]}, got {p['current']}"
                )

    def test_promotion_validity(self, report, packages):
        """Promoted-to level should not produce layered violations."""
        for p in report["promotable"]:
            pkg = packages[p["package"]]
            target = p["promoted_to"]
            if target in ("layered", "layered_dag", "dag"):
                my_rank = LAYER_ORDER[pkg["layer"]]
                for dep in pkg["dependencies"]:
                    dep_rank = LAYER_ORDER[packages[dep]["layer"]]
                    if dep_rank > my_rank:
                        pytest.fail(
                            f"{p['package']} promoted to {target} but depends on "
                            f"{dep} in higher layer"
                        )


# ============================================================
# Section 8: Migration plan (from corrected levels)
# ============================================================


class TestMigrationPlan:
    def test_steps_are_sequential(self, report):
        steps = report["migration_plan"]
        for i, s in enumerate(steps):
            assert s["step"] == i + 1, f"Step {i+1} has step number {s['step']}"

    def test_each_step_promotes_one_level(self, report):
        for s in report["migration_plan"]:
            from_idx = LEVEL_NAMES.index(s["from"])
            to_idx = LEVEL_NAMES.index(s["to"])
            assert to_idx == from_idx + 1, (
                f"Step {s['step']}: {s['from']} -> {s['to']} is not a single-level promotion"
            )

    def test_migration_ordering_valid(self, report, packages):
        """Each promotion must be valid at the time it occurs."""
        # Start from corrected levels
        corrected = {
            "db_driver": "layered",
            "queue_client": "false",
            "payment_model": "false",
            "analytics_model": "false",
            "order_api": "layered",
        }
        current = {}
        for n, p in packages.items():
            current[n] = corrected.get(n, p["strict_dependencies"])

        for s in report["migration_plan"]:
            pkg_name = s["package"]
            assert current[pkg_name] == s["from"], (
                f"Step {s['step']}: {pkg_name} should be at {s['from']} "
                f"but is at {current[pkg_name]}"
            )
            current[pkg_name] = s["to"]

    def test_migration_prefers_lower_layers(self, report, packages):
        """Lower-layer packages should be promoted before higher-layer packages."""
        steps = report["migration_plan"]
        if len(steps) < 2:
            return
        first_pkg = steps[0]["package"]
        assert LAYER_ORDER[packages[first_pkg]["layer"]] <= 1, (
            f"First promoted package should be utility or power layer, "
            f"got {packages[first_pkg]['layer']}"
        )

    def test_migration_step_count(self, report):
        """Should have exactly 38 migration steps."""
        assert len(report["migration_plan"]) == 38, (
            f"Expected 38 migration steps, got {len(report['migration_plan'])}"
        )

    def test_migration_reaches_correct_dag_count(self, report, packages):
        """Migration should result in exactly 9 packages at dag."""
        corrected = {
            "db_driver": "layered",
            "queue_client": "false",
            "payment_model": "false",
            "analytics_model": "false",
            "order_api": "layered",
        }
        current = {}
        for n, p in packages.items():
            current[n] = corrected.get(n, p["strict_dependencies"])
        for s in report["migration_plan"]:
            current[s["package"]] = s["to"]
        dag_count = sum(1 for v in current.values() if v == "dag")
        assert dag_count == 9, f"Expected 9 packages at dag, got {dag_count}"

    def test_migration_no_layered_violations(self, report, packages):
        """No step should promote a package that depends on a higher layer."""
        corrected = {
            "db_driver": "layered",
            "queue_client": "false",
            "payment_model": "false",
            "analytics_model": "false",
            "order_api": "layered",
        }
        current = {}
        for n, p in packages.items():
            current[n] = corrected.get(n, p["strict_dependencies"])
        for s in report["migration_plan"]:
            pkg = packages[s["package"]]
            new_level = s["to"]
            if new_level in ("layered", "layered_dag", "dag"):
                my_rank = LAYER_ORDER[pkg["layer"]]
                for dep in pkg["dependencies"]:
                    dep_rank = LAYER_ORDER[packages[dep]["layer"]]
                    if dep_rank > my_rank:
                        pytest.fail(
                            f"Step {s['step']}: promoting {s['package']} to {new_level} "
                            f"but it depends on {dep} in higher layer"
                        )
            current[s["package"]] = s["to"]


# ============================================================
# Section 9: Graph visualization
# ============================================================


class TestGraphVisualization:
    def test_svg_exists(self):
        assert os.path.exists("/app/output/graph.svg"), (
            "Dependency graph visualization must exist at /app/output/graph.svg"
        )

    def test_svg_is_valid(self):
        with open("/app/output/graph.svg") as f:
            content = f.read()
        assert "<svg" in content, "graph.svg must contain SVG markup"
        assert "</svg>" in content, "graph.svg must be complete SVG"

    def test_svg_contains_packages(self, packages):
        with open("/app/output/graph.svg") as f:
            content = f.read()
        found = sum(1 for name in packages if name in content)
        assert found >= 30, (
            f"SVG should reference most package names, found only {found}/34"
        )

    def test_svg_highlights_cycles(self):
        with open("/app/output/graph.svg") as f:
            content = f.read()
        content_lower = content.lower()
        has_red = (
            "red" in content_lower
            or "#ff0000" in content_lower
            or "ff0000" in content_lower
        )
        assert has_red, "SVG must highlight cycle-participating edges in red"

    def test_svg_groups_by_layer(self):
        with open("/app/output/graph.svg") as f:
            content = f.read()
        for layer in ["utility", "power", "business", "api", "services"]:
            assert layer in content, (
                f"SVG should group nodes by layer, missing '{layer}'"
            )


# ============================================================
# Section 10: Cross-section consistency
# ============================================================


class TestConsistency:
    def test_cycle_members_not_promotable_to_dag(self, report):
        """Packages in cycles should not be promotable to dag."""
        cycle_members = set()
        for scc in report["cycles"]:
            cycle_members.update(scc)
        for p in report["promotable"]:
            if p["package"] in cycle_members and p["promoted_to"] == "dag":
                pytest.fail(
                    f"{p['package']} is in a cycle but promotable to dag"
                )

    def test_invalid_packages_have_violations(self, report):
        """Every invalid-level package must appear in the violations list."""
        invalid_pkgs = {e["package"] for e in report["audit"]["invalid_levels"]}
        violation_pkgs = {v["package"] for v in report["violations"]}
        assert invalid_pkgs.issubset(violation_pkgs), (
            f"Invalid packages without violations: {invalid_pkgs - violation_pkgs}"
        )

    def test_undeclared_deps_in_complete_graph(self, report, packages):
        """Undeclared deps must be reflected in the analysis (complete graph)."""
        undeclared = {(d["source"], d["target"]) for d in report["audit"]["undeclared_dependencies"]}
        # Check that analytics_model->admin_api creates the admin_api SCC membership
        if ("analytics_model", "admin_api") in undeclared:
            large_sccs = [s for s in report["cycles"] if len(s) > 2]
            assert len(large_sccs) == 1
            assert "admin_api" in large_sccs[0], (
                "admin_api should be in the large SCC due to analytics_model->admin_api runtime dep"
            )

    def test_report_is_valid_json(self):
        with open("/app/output/report.json") as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_database_accessible(self):
        conn = sqlite3.connect("/app/monolith.db")
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM packages")
        count = cur.fetchone()[0]
        conn.close()
        assert count == 34, f"Expected 34 packages, got {count}"

    def test_runtime_scan_accessible(self):
        assert os.path.exists("/app/runtime_scan.csv"), "runtime_scan.csv must exist"
        with open("/app/runtime_scan.csv") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) > 50, f"Expected > 50 scan entries, got {len(rows)}"
