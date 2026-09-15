"""Tests for test suite coverage deduplication pipeline."""
import glob
import json
import os
import sqlite3

import pytest


DB_PATH = "/data/corpus.db"
TC_DB_PATH = "/data/corpus_test_cases.db"
REPORT_PATH = "/app/analysis_report.json"


def _ground_truth():
    """Compute ground-truth coverage data from the databases, properly filtering
    by repository status, node status, and data_status."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    tc_conn = sqlite3.connect(TC_DB_PATH)

    repos = conn.execute(
        "SELECT id, full_name FROM core_repository WHERE status = 'valid'"
    ).fetchall()
    gt = {}
    for repo in repos:
        nodes = conn.execute(
            """SELECT cn.id AS db_id, cn.node_id
               FROM core_node cn
               JOIN runtime_summary rs ON rs.node_id = cn.id
               WHERE cn.repo_id = ? AND rs.status IN ('passed', 'failed')""",
            (repo["id"],),
        ).fetchall()
        node_covs = {}
        for nd in nodes:
            tcs = tc_conn.execute(
                "SELECT coverage FROM runtime_test_case "
                "WHERE node_id = ? AND data_status IN (2, 3)",
                (nd["db_id"],),
            ).fetchall()
            cov = set()
            for tc in tcs:
                for fp, lines in json.loads(tc[0]).items():
                    for ln in lines:
                        cov.add((fp, ln))
            node_covs[nd["node_id"]] = cov
        gt[repo["full_name"]] = node_covs
    conn.close()
    tc_conn.close()
    return gt


def _jaccard(a, b):
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@pytest.fixture(scope="module")
def gt():
    return _ground_truth()


@pytest.fixture(scope="module")
def report():
    with open(REPORT_PATH) as f:
        return json.load(f)


# ── Report structure ─────────────────────────────────────────────────────────


class TestStructure:
    def test_report_exists(self):
        assert os.path.exists(REPORT_PATH), "Report not found at /app/analysis_report.json"

    def test_has_repositories_key(self, report):
        assert "repositories" in report
        assert isinstance(report["repositories"], dict)

    def test_all_repos_present(self, report, gt):
        for name in gt:
            assert name in report["repositories"], f"Missing repo {name}"

    def test_repo_fields(self, report):
        required = {
            "total_nodes",
            "total_lines_covered",
            "duplicate_pairs",
            "minimal_test_set",
            "minimal_set_size",
            "removed_nodes",
        }
        for name, data in report["repositories"].items():
            assert required <= set(data.keys()), f"Missing fields in {name}"

    def test_duplicate_pair_fields(self, report):
        for name, data in report["repositories"].items():
            for p in data["duplicate_pairs"]:
                assert {"node_a", "node_b", "jaccard_estimate"} <= set(p.keys())
                assert 0.0 <= p["jaccard_estimate"] <= 1.0


# ── Coverage aggregation ────────────────────────────────────────────────────


class TestAggregation:
    def test_total_nodes(self, report, gt):
        for name, covs in gt.items():
            assert report["repositories"][name]["total_nodes"] == len(covs), (
                f"{name}: expected {len(covs)} nodes"
            )

    def test_total_lines(self, report, gt):
        """Verifies correct aggregation — catches agents that read
        runtime_summary.coverage (which includes overrun/filtered coverage)."""
        for name, covs in gt.items():
            expected = len(set().union(*covs.values())) if covs else 0
            actual = report["repositories"][name]["total_lines_covered"]
            assert actual == expected, (
                f"{name}: expected {expected} total lines, got {actual}"
            )

    def test_error_nodes_excluded(self, report, gt):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        errors = conn.execute(
            """SELECT cn.node_id, cr.full_name
               FROM core_node cn
               JOIN core_repository cr ON cn.repo_id = cr.id
               JOIN runtime_summary rs ON rs.node_id = cn.id
               WHERE rs.status = 'error' AND cr.status = 'valid'"""
        ).fetchall()
        conn.close()
        for row in errors:
            rd = report["repositories"][row["full_name"]]
            all_nodes = set(rd["minimal_test_set"]) | set(rd["removed_nodes"])
            assert row["node_id"] not in all_nodes, (
                f"Error node {row['node_id']} should be excluded"
            )

    def test_skipped_nodes_excluded(self, report, gt):
        """Nodes with runtime_summary.status='skipped' must not appear."""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        skipped = conn.execute(
            """SELECT cn.node_id, cr.full_name
               FROM core_node cn
               JOIN core_repository cr ON cn.repo_id = cr.id
               JOIN runtime_summary rs ON rs.node_id = cn.id
               WHERE rs.status = 'skipped' AND cr.status = 'valid'"""
        ).fetchall()
        conn.close()
        for row in skipped:
            if row["full_name"] in report["repositories"]:
                rd = report["repositories"][row["full_name"]]
                all_nodes = set(rd["minimal_test_set"]) | set(rd["removed_nodes"])
                assert row["node_id"] not in all_nodes, (
                    f"Skipped node {row['node_id']} should be excluded"
                )

    def test_invalid_repos_excluded(self, report):
        """Repositories with status != 'valid' must not appear in report."""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        invalid = conn.execute(
            "SELECT full_name FROM core_repository WHERE status != 'valid'"
        ).fetchall()
        conn.close()
        for row in invalid:
            assert row["full_name"] not in report["repositories"], (
                f"Invalid repo {row['full_name']} should be excluded"
            )


# ── Duplicate detection ──────────────────────────────────────────────────────


class TestDuplicates:
    def test_no_false_positives(self, report, gt):
        """Reported duplicate pairs must have exact Jaccard >= 0.55."""
        for name, data in report["repositories"].items():
            covs = gt[name]
            for p in data["duplicate_pairs"]:
                j = _jaccard(
                    covs.get(p["node_a"], set()),
                    covs.get(p["node_b"], set()),
                )
                assert j >= 0.55, (
                    f"False positive in {name}: {p['node_a']} vs {p['node_b']} "
                    f"exact Jaccard={j:.3f} < 0.55"
                )

    def test_high_similarity_detected(self, report, gt):
        """Pairs with exact Jaccard >= 0.92 must be reported as duplicates."""
        for name, covs in gt.items():
            reported = set()
            for p in report["repositories"][name]["duplicate_pairs"]:
                reported.add(frozenset([p["node_a"], p["node_b"]]))
            nodes = list(covs.keys())
            for i in range(len(nodes)):
                for j_idx in range(i + 1, len(nodes)):
                    j_exact = _jaccard(covs[nodes[i]], covs[nodes[j_idx]])
                    if j_exact >= 0.92:
                        pair = frozenset([nodes[i], nodes[j_idx]])
                        assert pair in reported, (
                            f"Missed pair in {name}: {nodes[i]} vs {nodes[j_idx]} "
                            f"exact Jaccard={j_exact:.3f}"
                        )

    def test_estimates_reasonable(self, report, gt):
        """Reported Jaccard estimates must be within 0.20 of exact value."""
        for name, data in report["repositories"].items():
            covs = gt[name]
            for p in data["duplicate_pairs"]:
                exact = _jaccard(
                    covs.get(p["node_a"], set()),
                    covs.get(p["node_b"], set()),
                )
                assert abs(p["jaccard_estimate"] - exact) < 0.20, (
                    f"Bad estimate in {name}: est={p['jaccard_estimate']:.3f} "
                    f"exact={exact:.3f}"
                )

    def test_no_self_pairs(self, report):
        for name, data in report["repositories"].items():
            for p in data["duplicate_pairs"]:
                assert p["node_a"] != p["node_b"], "Self-pair detected"


# ── Minimal test set ─────────────────────────────────────────────────────────


class TestMinimalSet:
    def test_partition(self, report, gt):
        """minimal_test_set and removed_nodes must partition all analyzed nodes."""
        for name, covs in gt.items():
            rd = report["repositories"][name]
            minimal = set(rd["minimal_test_set"])
            removed = set(rd["removed_nodes"])
            expected = set(covs.keys())
            assert minimal | removed == expected, (
                f"Partition mismatch in {name}: "
                f"missing={expected - (minimal | removed)}, "
                f"extra={(minimal | removed) - expected}"
            )
            assert not (minimal & removed), f"Overlap in {name}: {minimal & removed}"

    def test_coverage_preserved(self, report, gt):
        """Minimal test set must cover all lines covered by the full set."""
        for name, covs in gt.items():
            rd = report["repositories"][name]
            full = set().union(*covs.values()) if covs else set()
            minimal_cov = set()
            for nid in rd["minimal_test_set"]:
                minimal_cov |= covs.get(nid, set())
            assert minimal_cov == full, (
                f"{name}: minimal set missing {len(full - minimal_cov)} lines"
            )

    def test_size_field(self, report):
        for name, rd in report["repositories"].items():
            assert rd["minimal_set_size"] == len(rd["minimal_test_set"])

    def test_not_larger_than_total(self, report):
        for name, rd in report["repositories"].items():
            assert rd["minimal_set_size"] <= rd["total_nodes"]


# ── Implementation constraints ───────────────────────────────────────────────


class TestImplementation:
    def test_no_external_similarity_libs(self):
        """Similarity computation must not use third-party libraries."""
        py_files = glob.glob("/app/**/*.py", recursive=True)
        forbidden = [
            "datasketch", "from minhash", "import minhash",
            "from sklearn", "import sklearn",
            "scipy.spatial.distance", "from scipy.spatial",
        ]
        for path in py_files:
            with open(path) as f:
                src = f.read().lower()
            for term in forbidden:
                assert term not in src, (
                    f"Must not use '{term}' in {path} — implement similarity yourself"
                )
