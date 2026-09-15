
import json
import os
import sys
import pytest

sys.path.insert(0, '/app')


@pytest.fixture(scope="module")
def report():
    report_path = "/app/signoff_report.json"
    assert os.path.exists(report_path), "signoff_report.json not found at /app/signoff_report.json"
    with open(report_path) as f:
        data = json.load(f)
    return data


@pytest.fixture(scope="module")
def proof_mgr_module():
    """Import proof_mgr module once for all tests."""
    import proof_mgr
    return proof_mgr


class TestReportStructure:
    def test_has_properties(self, report):
        assert "properties" in report
        assert isinstance(report["properties"], dict)

    def test_has_summary(self, report):
        assert "summary" in report
        assert isinstance(report["summary"], dict)

    def test_has_signoff_ready(self, report):
        assert "signoff_ready" in report
        assert isinstance(report["signoff_ready"], bool)

    def test_all_properties_present(self, report):
        expected_ids = {"P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P10"}
        assert set(report["properties"].keys()) == expected_ids

    def test_property_fields(self, report):
        for pid, pdata in report["properties"].items():
            assert "name" in pdata, f"{pid} missing 'name'"
            assert "status" in pdata, f"{pid} missing 'status'"
            assert "root_node" in pdata, f"{pid} missing 'root_node'"
            assert "issues" in pdata, f"{pid} missing 'issues'"
            assert isinstance(pdata["issues"], list), f"{pid} 'issues' should be a list"


class TestPropertyStatuses:
    """Verify each property's computed status against correct formal semantics."""

    def test_p1_mutual_exclusion_proven(self, report):
        """A-G with sound assumptions, all children proven -> proven."""
        assert report["properties"]["P1"]["status"] == "proven"

    def test_p2_status_override_proven(self, report):
        """Leaf with status_override=proven overrides engine inconclusive -> proven."""
        assert report["properties"]["P2"]["status"] == "proven"

    def test_p3_liveness_falsified(self, report):
        """Case split with one falsified case -> falsified."""
        assert report["properties"]["P3"]["status"] == "falsified"

    def test_p4_direct_circular_error(self, report):
        """A-G with direct circular dependency (N4a<->N4b) -> error."""
        assert report["properties"]["P4"]["status"] == "error"

    def test_p5_partition_falsified_inconclusive(self, report):
        """Partition with falsified child -> inconclusive (spurious CEX)."""
        assert report["properties"]["P5"]["status"] == "inconclusive"

    def test_p6_non_exhaustive_inconclusive(self, report):
        """Non-exhaustive case split with inconclusive case -> inconclusive."""
        assert report["properties"]["P6"]["status"] == "inconclusive"

    def test_p7_reset_proven(self, report):
        """Direct leaf proven -> proven."""
        assert report["properties"]["P7"]["status"] == "proven"

    def test_p8_ag_bounded_proven(self, report):
        """A-G with stopat(proven) child -> bounded_proven."""
        assert report["properties"]["P8"]["status"] == "bounded_proven"

    def test_p9_partition_stopat_bounded(self, report):
        """Partition -> stopat -> leaf(proven): partition preserves bounded_proven."""
        assert report["properties"]["P9"]["status"] == "bounded_proven"

    def test_p10_transitive_circular_error(self, report):
        """A-G with transitive circular dependency (A->C->B->A) -> error."""
        assert report["properties"]["P10"]["status"] == "error"


class TestCircularDependencyIssues:
    """Verify that circular dependency issues are properly reported."""

    def test_p4_issues_mention_circular(self, report):
        p4 = report["properties"]["P4"]
        issues_text = " ".join(p4["issues"]).lower()
        assert any(kw in issues_text for kw in ["circular", "cycle", "unsound"]), \
            f"P4 issues should mention circular dependency, got: {p4['issues']}"

    def test_p10_issues_mention_circular(self, report):
        """P10's transitive cycle must be detected and reported."""
        p10 = report["properties"]["P10"]
        issues_text = " ".join(p10["issues"]).lower()
        assert any(kw in issues_text for kw in ["circular", "cycle", "unsound"]), \
            f"P10 issues should mention circular dependency, got: {p10['issues']}"


class TestSignoffMetrics:
    """Test summary statistics and signoff coverage."""

    def test_total_properties(self, report):
        assert report["summary"]["total_properties"] == 10

    def test_proven_count(self, report):
        assert report["summary"]["proven"] == 3

    def test_bounded_proven_count(self, report):
        assert report["summary"]["bounded_proven"] == 2

    def test_falsified_count(self, report):
        assert report["summary"]["falsified"] == 1

    def test_inconclusive_count(self, report):
        assert report["summary"]["inconclusive"] == 2

    def test_error_count(self, report):
        assert report["summary"]["error"] == 2

    def test_signoff_coverage(self, report):
        coverage = report["summary"]["signoff_coverage"]
        assert abs(coverage - 0.3) < 0.001, f"Expected signoff_coverage ~0.3, got {coverage}"

    def test_signoff_not_ready(self, report):
        assert report["signoff_ready"] is False


class TestStatusConsistency:
    """Cross-check that summary counts match individual property statuses."""

    def test_counts_match_statuses(self, report):
        props = report["properties"]
        statuses = [p["status"] for p in props.values()]
        summary = report["summary"]
        assert statuses.count("proven") == summary["proven"]
        assert statuses.count("bounded_proven") == summary["bounded_proven"]
        assert statuses.count("falsified") == summary["falsified"]
        assert statuses.count("inconclusive") == summary["inconclusive"]
        assert statuses.count("error") == summary["error"]

    def test_total_equals_sum(self, report):
        s = report["summary"]
        total = s["proven"] + s["bounded_proven"] + s["falsified"] + s["inconclusive"] + s["error"]
        assert total == s["total_properties"]


class TestCycleDetectionFunction:
    """Directly test the cycle detection function for correctness."""

    def test_direct_mutual_cycle(self, proof_mgr_module):
        """Direct mutual dependency A<->B must be detected."""
        assumptions = {"A": ["B"], "B": ["A"]}
        found, nodes = proof_mgr_module.detect_circular_deps(assumptions)
        assert found is True

    def test_transitive_three_node_cycle(self, proof_mgr_module):
        """Transitive 3-node cycle A->C, B->A, C->B must be detected."""
        assumptions = {"A": ["C"], "B": ["A"], "C": ["B"]}
        found, nodes = proof_mgr_module.detect_circular_deps(assumptions)
        assert found is True

    def test_acyclic_chain(self, proof_mgr_module):
        """Acyclic assumption chain must not be flagged."""
        assumptions = {"A": [], "B": ["A"], "C": ["A", "B"]}
        found, nodes = proof_mgr_module.detect_circular_deps(assumptions)
        assert found is False

    def test_four_node_transitive_cycle(self, proof_mgr_module):
        """4-node transitive cycle must be detected."""
        assumptions = {"A": ["D"], "B": ["A"], "C": ["B"], "D": ["C"]}
        found, nodes = proof_mgr_module.detect_circular_deps(assumptions)
        assert found is True

    def test_five_node_transitive_cycle(self, proof_mgr_module):
        """5-node transitive cycle must be detected."""
        assumptions = {"A": ["E"], "B": ["A"], "C": ["B"], "D": ["C"], "E": ["D"]}
        found, nodes = proof_mgr_module.detect_circular_deps(assumptions)
        assert found is True

    def test_single_self_cycle(self, proof_mgr_module):
        """Self-dependency should be detected."""
        assumptions = {"A": ["A"]}
        found, nodes = proof_mgr_module.detect_circular_deps(assumptions)
        assert found is True


class TestCSVParsing:
    """Test that engine results CSV is correctly parsed."""

    def test_quoted_field_with_comma_parsed(self, proof_mgr_module):
        """CSV row with quoted engine_config containing comma must parse correctly."""
        results = proof_mgr_module.load_engine_results('/app/engine_results.csv')
        assert 'N9a1' in results
        assert results['N9a1']['status'] == 'proven', \
            f"N9a1 should be 'proven', got '{results['N9a1']['status']}'"

    def test_standard_fields_parsed(self, proof_mgr_module):
        """Standard rows without quoting issues must parse correctly."""
        results = proof_mgr_module.load_engine_results('/app/engine_results.csv')
        assert results['N1a']['status'] == 'proven'
        assert results['N3c']['status'] == 'falsified'
        assert results['N3c']['depth'] == 15
        assert results['N7']['status'] == 'proven'

    def test_inconclusive_engine_result(self, proof_mgr_module):
        """Rows with inconclusive status must parse correctly."""
        results = proof_mgr_module.load_engine_results('/app/engine_results.csv')
        assert results['N2']['status'] == 'inconclusive'
        assert results['N6d']['status'] == 'inconclusive'


class TestStatusOverride:
    """Test that status_override in proof structure takes precedence."""

    def test_override_applied_to_leaf(self, proof_mgr_module):
        """Leaf N2 with status_override=proven should return proven, not engine's inconclusive."""
        with open('/app/proof_structure.json') as f:
            data = json.load(f)
        nodes_by_id = {n['id']: n for n in data['proof_nodes']}
        engine_results = proof_mgr_module.load_engine_results('/app/engine_results.csv')

        status = proof_mgr_module.get_leaf_status(nodes_by_id['N2'], engine_results)
        assert status == "proven", \
            f"N2 has status_override=proven but get_leaf_status returned '{status}'"

    def test_no_override_uses_engine(self, proof_mgr_module):
        """Leaf without status_override should use engine result."""
        with open('/app/proof_structure.json') as f:
            data = json.load(f)
        nodes_by_id = {n['id']: n for n in data['proof_nodes']}
        engine_results = proof_mgr_module.load_engine_results('/app/engine_results.csv')

        status = proof_mgr_module.get_leaf_status(nodes_by_id['N7'], engine_results)
        assert status == "proven"


class TestPartitionBoundedProven:
    """Test partition strategy correctly handles bounded_proven child status."""

    def test_partition_preserves_bounded_proven(self, proof_mgr_module):
        """Partition with bounded_proven child (from stopat) must yield bounded_proven."""
        nodes = {
            'root': {'id': 'root', 'strategy': 'partition',
                     'blackboxed': ['m1'], 'children': ['st']},
            'st': {'id': 'st', 'strategy': 'stopat', 'bound': 100,
                   'children': ['leaf']},
            'leaf': {'id': 'leaf', 'strategy': 'leaf', 'scope': 'top',
                     'engine': 'test'}
        }
        engine = {'leaf': {'status': 'proven', 'depth': None}}
        memo = {}
        status, issues = proof_mgr_module.propagate_status('root', nodes, engine, memo)
        assert status == 'bounded_proven', \
            f"partition(stopat(proven)) should be bounded_proven, got '{status}'"


class TestNovelProofStructure:
    """Test with a novel proof structure not present in the task data."""

    def test_novel_ag_partition_stopat_composition(self, proof_mgr_module):
        """A-G with one proven leaf and one partition->stopat->leaf(proven) child."""
        nodes = {
            'R': {'id': 'R', 'strategy': 'assume_guarantee',
                  'children': ['A', 'B'],
                  'assumptions': {'A': [], 'B': ['A']}},
            'A': {'id': 'A', 'strategy': 'leaf', 'scope': 'mod1', 'engine': 'e1'},
            'B': {'id': 'B', 'strategy': 'partition', 'blackboxed': ['mod2'],
                  'children': ['B1']},
            'B1': {'id': 'B1', 'strategy': 'stopat', 'bound': 50,
                   'children': ['B1a']},
            'B1a': {'id': 'B1a', 'strategy': 'leaf', 'scope': 'top', 'engine': 'e2'}
        }
        engine = {
            'A': {'status': 'proven', 'depth': None},
            'B1a': {'status': 'proven', 'depth': None}
        }
        memo = {}
        status, issues = proof_mgr_module.propagate_status('R', nodes, engine, memo)
        # B1a proven -> B1 (stopat) bounded_proven -> B (partition) bounded_proven
        # A proven, B bounded_proven -> R = weaker(proven, bounded_proven) = bounded_proven
        assert status == 'bounded_proven', \
            f"Novel A-G(partition(stopat(proven))) should be bounded_proven, got '{status}'"

    def test_novel_partition_falsified_is_inconclusive(self, proof_mgr_module):
        """Partition with falsified child must yield inconclusive."""
        nodes = {
            'P': {'id': 'P', 'strategy': 'partition', 'blackboxed': ['x'],
                  'children': ['L']},
            'L': {'id': 'L', 'strategy': 'leaf', 'scope': 'top', 'engine': 'e'}
        }
        engine = {'L': {'status': 'falsified', 'depth': 5}}
        memo = {}
        status, _ = proof_mgr_module.propagate_status('P', nodes, engine, memo)
        assert status == 'inconclusive'

    def test_novel_override_in_propagation(self, proof_mgr_module):
        """Leaf with status_override in a larger tree must use the override."""
        nodes = {
            'R': {'id': 'R', 'strategy': 'assume_guarantee',
                  'children': ['X', 'Y'],
                  'assumptions': {'X': [], 'Y': ['X']}},
            'X': {'id': 'X', 'strategy': 'leaf', 'scope': 'mod',
                  'engine': 'e', 'status_override': 'proven'},
            'Y': {'id': 'Y', 'strategy': 'leaf', 'scope': 'mod', 'engine': 'e2'}
        }
        engine = {
            'X': {'status': 'inconclusive', 'depth': None},
            'Y': {'status': 'proven', 'depth': None}
        }
        memo = {}
        status, _ = proof_mgr_module.propagate_status('R', nodes, engine, memo)
        # X: override=proven, Y: engine=proven -> weaker(proven, proven) = proven
        assert status == 'proven', \
            f"Override should make X proven, overall should be proven, got '{status}'"


class TestPropertyNames:
    """Verify property names are correctly propagated."""

    def test_p1_name(self, report):
        assert report["properties"]["P1"]["name"] == "mutual_exclusion"

    def test_p3_name(self, report):
        assert report["properties"]["P3"]["name"] == "liveness"

    def test_p4_name(self, report):
        assert report["properties"]["P4"]["name"] == "fifo_no_overflow"

    def test_p9_name(self, report):
        assert report["properties"]["P9"]["name"] == "fairness"

    def test_p10_name(self, report):
        assert report["properties"]["P10"]["name"] == "deadlock_freedom"


class TestRootNodes:
    """Verify root node assignments."""

    def test_p1_root(self, report):
        assert report["properties"]["P1"]["root_node"] == "N1"

    def test_p2_root(self, report):
        assert report["properties"]["P2"]["root_node"] == "N2"

    def test_p3_root(self, report):
        assert report["properties"]["P3"]["root_node"] == "N3"

    def test_p4_root(self, report):
        assert report["properties"]["P4"]["root_node"] == "N4"

    def test_p5_root(self, report):
        assert report["properties"]["P5"]["root_node"] == "N5"

    def test_p6_root(self, report):
        assert report["properties"]["P6"]["root_node"] == "N6"

    def test_p7_root(self, report):
        assert report["properties"]["P7"]["root_node"] == "N7"

    def test_p8_root(self, report):
        assert report["properties"]["P8"]["root_node"] == "N8"

    def test_p9_root(self, report):
        assert report["properties"]["P9"]["root_node"] == "N9"

    def test_p10_root(self, report):
        assert report["properties"]["P10"]["root_node"] == "N10"
