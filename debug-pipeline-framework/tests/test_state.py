
"""
Verification tests for fault localization, root-cause clustering, and bug repair.

Checks:
  1. All pipeline bugs are fixed (test_suite.py passes)
  2. SBFL tool exists with correct formula functions and cluster_faults
  3. SBFL formulas produce mathematically correct results
  4. cluster_faults correctly groups lines by Jaccard similarity
  5. Output files have correct structure
  6. Cross-validation: fl_results.json consistent with coverage_matrix.json
  7. Localization quality metrics
  8. fault_clusters.json structure, consistency, and Jaccard invariants
"""
import pytest
import json
import subprocess
import sys
import os
import math
import importlib.util


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

def _ochiai_ref(ef, ep, nf, np_count):
    """Reference Ochiai implementation for cross-validation."""
    if ef == 0:
        return 0.0
    d = math.sqrt((ef + nf) * (ef + ep))
    return 0.0 if d == 0 else ef / d


def _import_fl_tool():
    """Import the solver's fl_tool.py as a module."""
    spec = importlib.util.spec_from_file_location("fl_tool", "/app/fl_tool.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _jaccard(set_a, set_b):
    """Compute Jaccard index of two sets."""
    if not set_a and not set_b:
        return 0.0
    inter = set_a & set_b
    union = set_a | set_b
    return len(inter) / len(union) if union else 0.0


def _failing_test_set(file_path, line_num, tests):
    """Compute the set of failing tests that execute a given line."""
    fail_set = set()
    for tid, tdata in tests.items():
        if not tdata['passed']:
            if line_num in tdata['covered_lines'].get(file_path, []):
                fail_set.add(tid)
    return fail_set


# ======================================================================
# 1. Pipeline bugs fixed
# ======================================================================

class TestPipelineFixed:

    def test_all_pipeline_tests_pass(self):
        """All tests in the original test suite must pass after fixes."""
        result = subprocess.run(
            ['python3', '-m', 'pytest', '/app/test_suite.py', '-v', '--tb=short'],
            capture_output=True, text=True, cwd='/app', timeout=120
        )
        assert result.returncode == 0, (
            f"Pipeline tests failed:\n{result.stdout}\n{result.stderr}"
        )


# ======================================================================
# 2. FL tool existence and importability
# ======================================================================

class TestFLToolExists:

    def test_fl_tool_importable(self):
        assert os.path.exists('/app/fl_tool.py'), "fl_tool.py not found at /app/"
        mod = _import_fl_tool()
        assert hasattr(mod, 'compute_ochiai'), "Missing compute_ochiai"
        assert hasattr(mod, 'compute_tarantula'), "Missing compute_tarantula"
        assert hasattr(mod, 'compute_dstar'), "Missing compute_dstar"

    def test_functions_callable(self):
        mod = _import_fl_tool()
        assert isinstance(mod.compute_ochiai(1, 1, 1, 1), (int, float))
        assert isinstance(mod.compute_tarantula(1, 1, 1, 1), (int, float))
        assert isinstance(mod.compute_dstar(1, 1, 1, 1), (int, float))

    def test_cluster_faults_callable(self):
        mod = _import_fl_tool()
        assert hasattr(mod, 'cluster_faults'), "Missing cluster_faults"
        cov = {"tests": {
            "t1": {"passed": False, "covered_lines": {"f.py": [1]}}
        }}
        rnk = {"formula": "ochiai", "rankings": {
            "f.py": [{"line": 1, "score": 0.5, "ef": 1, "ep": 0,
                       "nf": 0, "np": 0}]
        }}
        result = mod.cluster_faults(cov, rnk, threshold=0.6)
        assert isinstance(result, dict)
        assert 'clusters' in result


# ======================================================================
# 3. Ochiai formula
# ======================================================================

class TestOchiaiFormula:

    def test_basic(self):
        mod = _import_fl_tool()
        expected = 3 / math.sqrt(12)
        assert abs(mod.compute_ochiai(3, 1, 0, 6) - expected) < 1e-6

    def test_zero_ef(self):
        mod = _import_fl_tool()
        assert mod.compute_ochiai(0, 5, 3, 2) == 0.0

    def test_perfect_suspicion(self):
        mod = _import_fl_tool()
        assert abs(mod.compute_ochiai(5, 0, 0, 5) - 1.0) < 1e-6

    def test_symmetric(self):
        mod = _import_fl_tool()
        assert abs(mod.compute_ochiai(1, 1, 1, 1) - 0.5) < 1e-6

    def test_larger_values(self):
        mod = _import_fl_tool()
        expected = 10 / math.sqrt(12 * 15)
        assert abs(mod.compute_ochiai(10, 5, 2, 8) - expected) < 1e-6


# ======================================================================
# 4. Tarantula formula
# ======================================================================

class TestTarantulaFormula:

    def test_basic(self):
        mod = _import_fl_tool()
        # (3/5) / ((3/5) + (1/5)) = 0.6 / 0.8 = 0.75
        assert abs(mod.compute_tarantula(3, 1, 2, 4) - 0.75) < 1e-6

    def test_zero_ef(self):
        mod = _import_fl_tool()
        assert mod.compute_tarantula(0, 5, 3, 2) == 0.0

    def test_perfect_suspicion(self):
        mod = _import_fl_tool()
        assert abs(mod.compute_tarantula(5, 0, 0, 5) - 1.0) < 1e-6

    def test_mixed(self):
        mod = _import_fl_tool()
        # fail_rate=2/5, pass_rate=8/15 -> 0.4/(0.4+8/15) = 3/7
        expected = 3.0 / 7.0
        assert abs(mod.compute_tarantula(2, 8, 3, 7) - expected) < 1e-6


# ======================================================================
# 5. D* formula
# ======================================================================

class TestDStarFormula:

    def test_basic(self):
        mod = _import_fl_tool()
        # 3^2 / (2+1) = 9/3 = 3.0
        assert abs(mod.compute_dstar(3, 1, 2, 4) - 3.0) < 1e-6

    def test_zero_ef(self):
        mod = _import_fl_tool()
        assert mod.compute_dstar(0, 5, 3, 2) == 0.0

    def test_infinity(self):
        mod = _import_fl_tool()
        result = mod.compute_dstar(5, 0, 0, 5)
        assert result == float('inf') or result > 1e6, (
            f"Expected inf or very large, got {result}"
        )

    def test_mixed(self):
        mod = _import_fl_tool()
        # 2^2 / (3+8) = 4/11
        expected = 4.0 / 11.0
        assert abs(mod.compute_dstar(2, 8, 3, 7) - expected) < 1e-6

    def test_custom_star(self):
        mod = _import_fl_tool()
        # 3^3 / (2+1) = 27/3 = 9.0
        assert abs(mod.compute_dstar(3, 1, 2, 4, star=3) - 9.0) < 1e-6


# ======================================================================
# 6. cluster_faults function behavior
# ======================================================================

class TestClusterFaultsFunction:

    def test_identical_sets_same_cluster(self):
        """Lines with identical failing-test sets belong to the same cluster."""
        mod = _import_fl_tool()
        coverage = {
            "tests": {
                "t_a": {"passed": False, "covered_lines": {"f.py": [1, 2]}},
                "t_b": {"passed": False, "covered_lines": {"f.py": [1, 2]}},
                "t_c": {"passed": True, "covered_lines": {"f.py": [1]}},
                "t_d": {"passed": True, "covered_lines": {"g.py": [10]}},
            }
        }
        rankings = {
            "formula": "ochiai",
            "rankings": {
                "f.py": [
                    {"line": 1, "score": 0.8, "ef": 2, "ep": 1,
                     "nf": 0, "np": 1},
                    {"line": 2, "score": 0.7, "ef": 2, "ep": 0,
                     "nf": 0, "np": 2},
                ],
            }
        }
        result = mod.cluster_faults(coverage, rankings, threshold=0.5)
        # Both lines fail on t_a and t_b: Jaccard = 1.0 >= 0.5
        assert result['num_clusters'] == 1
        assert len(result['clusters'][0]['lines']) == 2

    def test_disjoint_sets_different_clusters(self):
        """Lines with disjoint failing-test sets belong to different clusters."""
        mod = _import_fl_tool()
        coverage = {
            "tests": {
                "t_a": {"passed": False, "covered_lines": {"f.py": [1]}},
                "t_b": {"passed": False, "covered_lines": {"g.py": [10]}},
                "t_c": {"passed": True, "covered_lines": {
                    "f.py": [1], "g.py": [10]
                }},
            }
        }
        rankings = {
            "formula": "ochiai",
            "rankings": {
                "f.py": [
                    {"line": 1, "score": 0.7, "ef": 1, "ep": 0,
                     "nf": 1, "np": 1},
                ],
                "g.py": [
                    {"line": 10, "score": 0.7, "ef": 1, "ep": 0,
                     "nf": 1, "np": 1},
                ],
            }
        }
        result = mod.cluster_faults(coverage, rankings, threshold=0.5)
        # Line 1: fails={t_a}, Line 10: fails={t_b}, Jaccard=0.0 < 0.5
        assert result['num_clusters'] == 2

    def test_transitive_clustering(self):
        """Connected-component semantics: A~B, B~C ⇒ A,B,C in one cluster."""
        mod = _import_fl_tool()
        coverage = {
            "tests": {
                "t1": {"passed": False, "covered_lines": {"f.py": [1]}},
                "t2": {"passed": False, "covered_lines": {"f.py": [1, 2]}},
                "t3": {"passed": False, "covered_lines": {"f.py": [1, 2, 3]}},
                "t4": {"passed": False, "covered_lines": {"f.py": [2, 3]}},
                "t5": {"passed": False, "covered_lines": {"f.py": [3]}},
                "t6": {"passed": True, "covered_lines": {"f.py": [1]}},
            }
        }
        rankings = {
            "formula": "ochiai",
            "rankings": {
                "f.py": [
                    {"line": 1, "score": 0.8, "ef": 3, "ep": 1,
                     "nf": 2, "np": 0},
                    {"line": 2, "score": 0.7, "ef": 3, "ep": 0,
                     "nf": 2, "np": 1},
                    {"line": 3, "score": 0.6, "ef": 3, "ep": 0,
                     "nf": 2, "np": 1},
                ],
            }
        }
        result = mod.cluster_faults(coverage, rankings, threshold=0.5)
        # A={t1,t2,t3} B={t2,t3,t4} C={t3,t4,t5}
        # J(A,B)=2/4=0.5>=0.5  J(B,C)=2/4=0.5>=0.5  J(A,C)=1/5=0.2<0.5
        # Connected via chain A-B-C => one cluster
        assert result['num_clusters'] == 1
        assert len(result['clusters'][0]['lines']) == 3


# ======================================================================
# 7. fl_results.json structure
# ======================================================================

class TestFLResultsStructure:

    def test_file_exists(self):
        assert os.path.exists('/app/fl_results.json'), \
            "fl_results.json not found at /app/"

    def test_has_formula_ochiai(self):
        with open('/app/fl_results.json') as f:
            data = json.load(f)
        assert data.get('formula') == 'ochiai'

    def test_has_rankings_for_multiple_files(self):
        with open('/app/fl_results.json') as f:
            data = json.load(f)
        assert 'rankings' in data
        assert isinstance(data['rankings'], dict)
        assert len(data['rankings']) >= 3, \
            f"Expected rankings for >=3 files, got {len(data['rankings'])}"

    def test_ranking_entry_fields(self):
        with open('/app/fl_results.json') as f:
            data = json.load(f)
        for fpath, entries in data['rankings'].items():
            assert isinstance(entries, list), f"Rankings for {fpath} not a list"
            for entry in entries[:5]:
                for key in ('line', 'score', 'ef', 'ep', 'nf', 'np'):
                    assert key in entry, \
                        f"Missing '{key}' in {fpath} entry: {entry}"
                assert isinstance(entry['line'], int)
                assert isinstance(entry['score'], (int, float))

    def test_rankings_sorted_descending(self):
        with open('/app/fl_results.json') as f:
            data = json.load(f)
        for fpath, entries in data['rankings'].items():
            scores = [e['score'] for e in entries]
            for i in range(len(scores) - 1):
                assert scores[i] >= scores[i + 1], (
                    f"Not sorted in {fpath}: "
                    f"score[{i}]={scores[i]} < score[{i+1}]={scores[i+1]}"
                )

    def test_relative_paths(self):
        with open('/app/fl_results.json') as f:
            data = json.load(f)
        for fpath in data['rankings']:
            assert not fpath.startswith('/'), \
                f"Path should be relative, got: {fpath}"


# ======================================================================
# 8. coverage_matrix.json structure
# ======================================================================

class TestCoverageMatrixStructure:

    def test_file_exists(self):
        assert os.path.exists('/app/coverage_matrix.json'), \
            "coverage_matrix.json not found at /app/"

    def test_has_tests_dict(self):
        with open('/app/coverage_matrix.json') as f:
            data = json.load(f)
        assert 'tests' in data
        assert isinstance(data['tests'], dict)
        assert len(data['tests']) >= 20, \
            f"Expected >=20 tests, got {len(data['tests'])}"

    def test_entry_structure(self):
        with open('/app/coverage_matrix.json') as f:
            data = json.load(f)
        for tid, info in data['tests'].items():
            assert 'passed' in info, f"Missing 'passed' in {tid}"
            assert 'covered_lines' in info, f"Missing 'covered_lines' in {tid}"
            assert isinstance(info['passed'], bool), \
                f"'passed' not bool in {tid}"
            assert isinstance(info['covered_lines'], dict), \
                f"'covered_lines' not dict in {tid}"

    def test_has_passing_and_failing(self):
        with open('/app/coverage_matrix.json') as f:
            data = json.load(f)
        passing = sum(1 for t in data['tests'].values() if t['passed'])
        failing = sum(1 for t in data['tests'].values() if not t['passed'])
        assert passing >= 5, f"Expected >=5 passing, got {passing}"
        assert failing >= 10, f"Expected >=10 failing, got {failing}"

    def test_covers_pipeweave_files(self):
        with open('/app/coverage_matrix.json') as f:
            data = json.load(f)
        all_files = set()
        for info in data['tests'].values():
            all_files.update(info['covered_lines'].keys())
        pw_files = [f for f in all_files if 'pipeweave' in f]
        assert len(pw_files) >= 3, \
            f"Expected >=3 pipeweave files in coverage, got {pw_files}"


# ======================================================================
# 9. Cross-validation: fl_results <-> coverage_matrix consistency
# ======================================================================

class TestCrossValidation:

    def _load_both(self):
        with open('/app/coverage_matrix.json') as f:
            matrix = json.load(f)
        with open('/app/fl_results.json') as f:
            results = json.load(f)
        return matrix, results

    def test_ef_ep_match_coverage_matrix(self):
        """ef/ep in results must match counts derived from coverage matrix."""
        matrix, results = self._load_both()
        tests = matrix['tests']

        for fpath, entries in results['rankings'].items():
            for entry in entries[:5]:
                line = entry['line']
                ef_computed = 0
                ep_computed = 0
                for tdata in tests.values():
                    if line in tdata['covered_lines'].get(fpath, []):
                        if tdata['passed']:
                            ep_computed += 1
                        else:
                            ef_computed += 1
                assert entry['ef'] == ef_computed, (
                    f"ef mismatch {fpath}:{line}: "
                    f"result={entry['ef']}, matrix={ef_computed}"
                )
                assert entry['ep'] == ep_computed, (
                    f"ep mismatch {fpath}:{line}: "
                    f"result={entry['ep']}, matrix={ep_computed}"
                )

    def test_ochiai_scores_match(self):
        """Ochiai scores must be mathematically correct given ef/ep/nf/np."""
        _, results = self._load_both()
        for fpath, entries in results['rankings'].items():
            for entry in entries[:5]:
                expected = _ochiai_ref(
                    entry['ef'], entry['ep'], entry['nf'], entry['np']
                )
                assert abs(entry['score'] - expected) < 1e-4, (
                    f"Ochiai mismatch {fpath}:{entry['line']}: "
                    f"result={entry['score']:.6f}, expected={expected:.6f}"
                )

    def test_nf_np_totals_consistent(self):
        """ef+nf must equal total_failed; ep+np must equal total_passed."""
        matrix, results = self._load_both()
        total_failed = sum(1 for t in matrix['tests'].values()
                          if not t['passed'])
        total_passed = sum(1 for t in matrix['tests'].values()
                          if t['passed'])

        for fpath, entries in results['rankings'].items():
            for entry in entries[:5]:
                assert entry['ef'] + entry['nf'] == total_failed, (
                    f"ef+nf != total_failed for {fpath}:{entry['line']}"
                )
                assert entry['ep'] + entry['np'] == total_passed, (
                    f"ep+np != total_passed for {fpath}:{entry['line']}"
                )


# ======================================================================
# 10. Localization quality
# ======================================================================

class TestLocalizationQuality:

    def test_buggy_files_in_rankings(self):
        with open('/app/fl_results.json') as f:
            data = json.load(f)
        ranked = set(data['rankings'].keys())
        modules = ['config.py', 'engine.py', 'transforms.py',
                    'formatter.py', 'schema.py']
        found = sum(1 for m in modules
                    if any(m in rf for rf in ranked))
        assert found >= 4, \
            f"Expected >=4 buggy modules in rankings, found {found}"

    def test_nonzero_scores_exist(self):
        with open('/app/fl_results.json') as f:
            data = json.load(f)
        total = sum(
            1 for entries in data['rankings'].values()
            for e in entries if e['score'] > 0
        )
        assert total >= 10, \
            f"Expected >=10 lines with score>0, got {total}"

    def test_high_suspicion_lines(self):
        """Some lines should have meaningful suspiciousness (>0.3 Ochiai)."""
        with open('/app/fl_results.json') as f:
            data = json.load(f)
        high = sum(
            1 for entries in data['rankings'].values()
            for e in entries if e['score'] > 0.3
        )
        assert high >= 5, \
            f"Expected >=5 lines with score>0.3, got {high}"


# ======================================================================
# 11. fault_clusters.json structure and consistency
# ======================================================================

class TestFaultClustersOutput:

    def test_file_exists(self):
        assert os.path.exists('/app/fault_clusters.json'), \
            "fault_clusters.json not found at /app/"

    def test_schema_valid(self):
        with open('/app/fault_clusters.json') as f:
            data = json.load(f)
        assert data.get('method') == 'jaccard', \
            f"Expected method 'jaccard', got {data.get('method')}"
        assert isinstance(data.get('threshold'), (int, float))
        assert isinstance(data.get('num_clusters'), int)
        assert isinstance(data.get('clusters'), list)
        assert data['num_clusters'] == len(data['clusters']), \
            "num_clusters doesn't match len(clusters)"

    def test_threshold_in_range(self):
        with open('/app/fault_clusters.json') as f:
            data = json.load(f)
        assert 0.5 <= data['threshold'] <= 0.8, \
            f"Threshold {data['threshold']} not in [0.5, 0.8]"

    def test_minimum_clusters(self):
        with open('/app/fault_clusters.json') as f:
            data = json.load(f)
        assert data['num_clusters'] >= 3, \
            f"Expected >=3 clusters, got {data['num_clusters']}"

    def test_cluster_entry_structure(self):
        with open('/app/fault_clusters.json') as f:
            data = json.load(f)
        for cluster in data['clusters']:
            assert 'id' in cluster, "Missing 'id' in cluster"
            assert 'lines' in cluster, "Missing 'lines' in cluster"
            assert 'failing_tests' in cluster, "Missing 'failing_tests'"
            assert 'modules_involved' in cluster, "Missing 'modules_involved'"
            assert isinstance(cluster['lines'], list)
            assert len(cluster['lines']) > 0, \
                f"Cluster {cluster['id']} has no lines"
            for li in cluster['lines']:
                assert 'file' in li, f"Missing 'file' in line entry"
                assert 'line' in li, f"Missing 'line' in line entry"
                assert 'score' in li, f"Missing 'score' in line entry"

    def test_no_duplicate_lines_across_clusters(self):
        with open('/app/fault_clusters.json') as f:
            data = json.load(f)
        seen = set()
        for cluster in data['clusters']:
            for li in cluster['lines']:
                key = (li['file'], li['line'])
                assert key not in seen, \
                    f"Line {key} appears in multiple clusters"
                seen.add(key)

    def test_failing_tests_match_coverage(self):
        """Each cluster's failing_tests = union from coverage matrix."""
        with open('/app/coverage_matrix.json') as f:
            matrix = json.load(f)
        with open('/app/fault_clusters.json') as f:
            clusters_data = json.load(f)
        tests = matrix['tests']
        for cluster in clusters_data['clusters']:
            expected = set()
            for li in cluster['lines']:
                expected.update(
                    _failing_test_set(li['file'], li['line'], tests)
                )
            actual = set(cluster['failing_tests'])
            assert actual == expected, (
                f"Cluster {cluster['id']}: failing_tests mismatch. "
                f"Missing: {expected - actual}, Extra: {actual - expected}"
            )

    def test_no_cross_cluster_jaccard_exceeds_threshold(self):
        """No line pair across different clusters may have Jaccard >= threshold."""
        with open('/app/coverage_matrix.json') as f:
            matrix = json.load(f)
        with open('/app/fault_clusters.json') as f:
            clusters_data = json.load(f)
        threshold = clusters_data['threshold']
        tests = matrix['tests']

        # Compute unique failing-test-set signatures per cluster
        cluster_unique_sets = []
        for cluster in clusters_data['clusters']:
            unique = set()
            for li in cluster['lines']:
                fs = frozenset(
                    _failing_test_set(li['file'], li['line'], tests)
                )
                unique.add(fs)
            cluster_unique_sets.append(unique)

        for i in range(len(cluster_unique_sets)):
            for j in range(i + 1, len(cluster_unique_sets)):
                for sa in cluster_unique_sets[i]:
                    for sb in cluster_unique_sets[j]:
                        if not sa or not sb:
                            continue
                        jac = _jaccard(sa, sb)
                        assert jac < threshold, (
                            f"Cross-cluster Jaccard {jac:.4f} >= "
                            f"threshold {threshold} "
                            f"(clusters {i} and {j})"
                        )

    def test_clusters_sorted_by_max_score(self):
        with open('/app/fault_clusters.json') as f:
            data = json.load(f)
        if len(data['clusters']) < 2:
            return
        max_scores = [
            max(l['score'] for l in c['lines'])
            for c in data['clusters']
        ]
        for i in range(len(max_scores) - 1):
            assert max_scores[i] >= max_scores[i + 1], (
                f"Clusters not sorted: score {max_scores[i]} < "
                f"{max_scores[i+1]} at positions {i}, {i+1}"
            )

    def test_modules_involved_correct(self):
        with open('/app/fault_clusters.json') as f:
            data = json.load(f)
        for cluster in data['clusters']:
            expected = sorted(set(l['file'] for l in cluster['lines']))
            assert cluster['modules_involved'] == expected, (
                f"Cluster {cluster['id']}: modules_involved mismatch. "
                f"Expected {expected}, got {cluster['modules_involved']}"
            )
