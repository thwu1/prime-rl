
import json
import os
import pytest


@pytest.fixture(scope="module")
def report():
    report_path = "/app/report.json"
    assert os.path.isfile(report_path), "report.json must exist at /app/report.json"
    with open(report_path) as f:
        data = json.load(f)
    return data


class TestReportStructure:
    def test_top_level_keys(self, report):
        required_keys = [
            "operations",
            "operation_dependency_graph",
            "tool_metrics",
            "z_scores",
            "ranking",
            "badges",
        ]
        for key in required_keys:
            assert key in report, f"Missing top-level key: {key}"

    def test_operations_is_list(self, report):
        assert isinstance(report["operations"], list)

    def test_operations_count(self, report):
        assert len(report["operations"]) == 16, (
            f"Expected 16 operations, got {len(report['operations'])}"
        )

    def test_operations_have_required_fields(self, report):
        for op in report["operations"]:
            assert "operationId" in op, "Operation missing operationId"
            assert "method" in op, "Operation missing method"
            assert "path" in op, "Operation missing path"


class TestToolMetrics:
    def test_all_tools_present(self, report):
        metrics = report["tool_metrics"]
        assert "tool_alpha" in metrics
        assert "tool_beta" in metrics
        assert "tool_gamma" in metrics

    def test_tool_alpha_operations_covered(self, report):
        m = report["tool_metrics"]["tool_alpha"]
        assert m["operations_covered"] == 13, (
            f"tool_alpha should cover 13 operations, got {m['operations_covered']}"
        )

    def test_tool_beta_operations_covered(self, report):
        m = report["tool_metrics"]["tool_beta"]
        assert m["operations_covered"] == 8, (
            f"tool_beta should cover 8 operations, got {m['operations_covered']}"
        )

    def test_tool_gamma_operations_covered(self, report):
        m = report["tool_metrics"]["tool_gamma"]
        assert m["operations_covered"] == 5, (
            f"tool_gamma should cover 5 operations, got {m['operations_covered']}"
        )

    def test_tool_alpha_faults(self, report):
        m = report["tool_metrics"]["tool_alpha"]
        assert m["unique_faults"] == 5, (
            f"tool_alpha should have 5 unique faults, got {m['unique_faults']}"
        )

    def test_tool_beta_faults(self, report):
        m = report["tool_metrics"]["tool_beta"]
        assert m["unique_faults"] == 3, (
            f"tool_beta should have 3 unique faults, got {m['unique_faults']}"
        )

    def test_tool_gamma_faults(self, report):
        m = report["tool_metrics"]["tool_gamma"]
        assert m["unique_faults"] == 1, (
            f"tool_gamma should have 1 unique fault, got {m['unique_faults']}"
        )

    def test_total_operations_consistent(self, report):
        for tool_name, m in report["tool_metrics"].items():
            assert m["total_operations"] == 16, (
                f"{tool_name} total_operations should be 16, got {m['total_operations']}"
            )

    def test_tool_alpha_status_distribution(self, report):
        d = report["tool_metrics"]["tool_alpha"]["status_code_distribution"]
        assert "2xx" in d and "4xx" in d and "5xx" in d
        assert d["5xx"] == 5, f"tool_alpha 5xx count should be 5, got {d['5xx']}"
        assert d["2xx"] == 14, f"tool_alpha 2xx count should be 14, got {d['2xx']}"

    def test_coverage_ratio(self, report):
        for tool_name, m in report["tool_metrics"].items():
            expected = m["operations_covered"] / m["total_operations"]
            assert abs(m["operation_coverage_ratio"] - expected) < 0.01, (
                f"{tool_name} coverage ratio mismatch"
            )


class TestCodeCoverage:
    """Verify JaCoCo coverage ratios extracted from XML reports."""

    def test_tool_alpha_branch_coverage(self, report):
        m = report["tool_metrics"]["tool_alpha"]
        # JaCoCo: BRANCH missed=48 covered=200 -> 200/248 ≈ 0.8065
        assert abs(m["branch_coverage"] - 0.8065) < 0.01, (
            f"tool_alpha branch_coverage expected ~0.8065, got {m['branch_coverage']}"
        )

    def test_tool_beta_branch_coverage(self, report):
        m = report["tool_metrics"]["tool_beta"]
        # JaCoCo: BRANCH missed=120 covered=90 -> 90/210 ≈ 0.4286
        assert abs(m["branch_coverage"] - 0.4286) < 0.01, (
            f"tool_beta branch_coverage expected ~0.4286, got {m['branch_coverage']}"
        )

    def test_tool_gamma_branch_coverage(self, report):
        m = report["tool_metrics"]["tool_gamma"]
        # JaCoCo: BRANCH missed=149 covered=35 -> 35/184 ≈ 0.1902
        assert abs(m["branch_coverage"] - 0.1902) < 0.01, (
            f"tool_gamma branch_coverage expected ~0.1902, got {m['branch_coverage']}"
        )

    def test_tool_alpha_line_coverage(self, report):
        m = report["tool_metrics"]["tool_alpha"]
        # LINE missed=60 covered=265 -> 265/325 ≈ 0.8154
        assert abs(m["line_coverage"] - 0.8154) < 0.01, (
            f"tool_alpha line_coverage expected ~0.8154, got {m['line_coverage']}"
        )

    def test_tool_alpha_method_coverage(self, report):
        m = report["tool_metrics"]["tool_alpha"]
        # METHOD missed=4 covered=45 -> 45/49 ≈ 0.9184
        assert abs(m["method_coverage"] - 0.9184) < 0.01, (
            f"tool_alpha method_coverage expected ~0.9184, got {m['method_coverage']}"
        )

    def test_tool_gamma_method_coverage(self, report):
        m = report["tool_metrics"]["tool_gamma"]
        # METHOD missed=23 covered=16 -> 16/39 ≈ 0.4103
        assert abs(m["method_coverage"] - 0.4103) < 0.01, (
            f"tool_gamma method_coverage expected ~0.4103, got {m['method_coverage']}"
        )

    def test_coverage_ordering(self, report):
        alpha_b = report["tool_metrics"]["tool_alpha"]["branch_coverage"]
        beta_b = report["tool_metrics"]["tool_beta"]["branch_coverage"]
        gamma_b = report["tool_metrics"]["tool_gamma"]["branch_coverage"]
        assert alpha_b > beta_b > gamma_b, (
            f"Branch coverage ordering should be alpha > beta > gamma, "
            f"got {alpha_b}, {beta_b}, {gamma_b}"
        )


class TestRankingAndBadges:
    def test_ranking_order(self, report):
        ranking = report["ranking"]
        assert ranking == ["tool_alpha", "tool_beta", "tool_gamma"], (
            f"Expected ranking [alpha, beta, gamma], got {ranking}"
        )

    def test_gold_badge(self, report):
        assert report["badges"]["gold_api_tester"] == "tool_alpha"

    def test_bug_hunter_badge(self, report):
        assert report["badges"]["bug_hunter"] == "tool_alpha"


class TestZScores:
    def test_all_tools_have_z_scores(self, report):
        for tool in ["tool_alpha", "tool_beta", "tool_gamma"]:
            assert tool in report["z_scores"]
            z = report["z_scores"][tool]
            assert "operation_coverage" in z
            assert "fault_detection" in z
            assert "branch_coverage" in z
            assert "composite" in z

    def test_alpha_z_scores_positive(self, report):
        z = report["z_scores"]["tool_alpha"]
        assert z["composite"] > 0, (
            f"tool_alpha composite z-score should be positive, got {z['composite']}"
        )

    def test_gamma_z_scores_negative(self, report):
        z = report["z_scores"]["tool_gamma"]
        assert z["composite"] < 0, (
            f"tool_gamma composite z-score should be negative, got {z['composite']}"
        )

    def test_z_score_ordering(self, report):
        z = report["z_scores"]
        assert z["tool_alpha"]["composite"] > z["tool_beta"]["composite"], (
            "tool_alpha composite should exceed tool_beta"
        )
        assert z["tool_beta"]["composite"] > z["tool_gamma"]["composite"], (
            "tool_beta composite should exceed tool_gamma"
        )

    def test_alpha_op_coverage_z_approximate(self, report):
        z = report["z_scores"]["tool_alpha"]["operation_coverage"]
        # Expected ~1.3131
        assert abs(z - 1.3131) < 0.15, (
            f"tool_alpha op coverage z-score expected ~1.31, got {z}"
        )

    def test_alpha_fault_z_approximate(self, report):
        z = report["z_scores"]["tool_alpha"]["fault_detection"]
        # Expected ~1.2247
        assert abs(z - 1.2247) < 0.15, (
            f"tool_alpha fault z-score expected ~1.22, got {z}"
        )

    def test_alpha_branch_z_approximate(self, report):
        z = report["z_scores"]["tool_alpha"]["branch_coverage"]
        # Expected ~1.31 (branch coverage z-score)
        assert abs(z - 1.31) < 0.15, (
            f"tool_alpha branch coverage z-score expected ~1.31, got {z}"
        )

    def test_composite_is_sum_of_three(self, report):
        for tool in ["tool_alpha", "tool_beta", "tool_gamma"]:
            z = report["z_scores"][tool]
            expected = z["operation_coverage"] + z["fault_detection"] + z["branch_coverage"]
            assert abs(z["composite"] - expected) < 0.01, (
                f"{tool} composite should be sum of three z-scores, "
                f"expected {expected}, got {z['composite']}"
            )

    def test_alpha_composite_approximate(self, report):
        z = report["z_scores"]["tool_alpha"]["composite"]
        # Expected ~3.84 (sum of three positive z-scores)
        assert abs(z - 3.84) < 0.3, (
            f"tool_alpha composite expected ~3.84, got {z}"
        )


class TestODG:
    def test_odg_is_dict(self, report):
        odg = report["operation_dependency_graph"]
        assert isinstance(odg, dict)

    def test_all_operations_in_odg(self, report):
        odg = report["operation_dependency_graph"]
        assert len(odg) == 16, (
            f"ODG should have 16 keys (one per operation), got {len(odg)}"
        )

    def test_create_user_to_get_user(self, report):
        odg = report["operation_dependency_graph"]
        assert "getUser" in odg.get("createUser", []), (
            "ODG should have edge createUser -> getUser"
        )

    def test_create_user_to_delete_user(self, report):
        odg = report["operation_dependency_graph"]
        assert "deleteUser" in odg.get("createUser", []), (
            "ODG should have edge createUser -> deleteUser"
        )

    def test_create_user_to_update_user(self, report):
        odg = report["operation_dependency_graph"]
        assert "updateUser" in odg.get("createUser", []), (
            "ODG should have edge createUser -> updateUser"
        )

    def test_create_project_to_get_project(self, report):
        odg = report["operation_dependency_graph"]
        assert "getProject" in odg.get("createProject", []), (
            "ODG should have edge createProject -> getProject"
        )

    def test_create_project_to_create_task(self, report):
        odg = report["operation_dependency_graph"]
        assert "createTask" in odg.get("createProject", []), (
            "ODG should have edge createProject -> createTask"
        )

    def test_create_task_to_get_task(self, report):
        odg = report["operation_dependency_graph"]
        assert "getTask" in odg.get("createTask", []), (
            "ODG should have edge createTask -> getTask"
        )

    def test_create_task_to_add_comment(self, report):
        odg = report["operation_dependency_graph"]
        assert "addComment" in odg.get("createTask", []), (
            "ODG should have edge createTask -> addComment"
        )

    def test_create_task_to_update_task(self, report):
        odg = report["operation_dependency_graph"]
        assert "updateTask" in odg.get("createTask", []), (
            "ODG should have edge createTask -> updateTask"
        )

    def test_login_no_outgoing_edges(self, report):
        odg = report["operation_dependency_graph"]
        assert odg.get("login", []) == [], (
            f"login should have no outgoing edges, got {odg.get('login', [])}"
        )

    def test_delete_user_no_outgoing_edges(self, report):
        odg = report["operation_dependency_graph"]
        assert odg.get("deleteUser", []) == [], (
            f"deleteUser should have no outgoing edges (no response body), "
            f"got {odg.get('deleteUser', [])}"
        )

    def test_no_self_loops(self, report):
        odg = report["operation_dependency_graph"]
        for op_id, deps in odg.items():
            assert op_id not in deps, (
                f"ODG should have no self-loops, but {op_id} depends on itself"
            )

    def test_create_user_to_add_project_member(self, report):
        odg = report["operation_dependency_graph"]
        assert "addProjectMember" in odg.get("createUser", []), (
            "ODG should have edge createUser -> addProjectMember (userId match)"
        )


class TestGraphOutputs:
    """Verify Graphviz DOT and SVG outputs."""

    def test_dot_file_exists(self):
        assert os.path.isfile("/app/odg.dot"), (
            "odg.dot must exist at /app/odg.dot"
        )

    def test_dot_contains_digraph(self):
        with open("/app/odg.dot") as f:
            content = f.read()
        assert "digraph" in content.lower(), (
            "odg.dot should contain a 'digraph' declaration"
        )

    def test_dot_contains_expected_edge(self):
        with open("/app/odg.dot") as f:
            content = f.read()
        assert "createUser" in content and "getUser" in content, (
            "odg.dot should contain nodes createUser and getUser"
        )
        assert "->" in content, (
            "odg.dot should contain directed edges (->)"
        )

    def test_svg_file_exists(self):
        assert os.path.isfile("/app/odg.svg"), (
            "odg.svg must exist at /app/odg.svg"
        )

    def test_svg_is_valid(self):
        with open("/app/odg.svg") as f:
            content = f.read()
        assert "<svg" in content.lower(), (
            "odg.svg should contain an <svg> element"
        )
        assert len(content) > 100, (
            "odg.svg should not be empty/trivial"
        )
