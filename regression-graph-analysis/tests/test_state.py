
import csv
import json
import os
import sys

import networkx as nx
import pytest

csv.field_size_limit(sys.maxsize)

RESULTS_PATH = "/app/results.json"
DATASET_PATH = "/app/dataset.csv"


def load_results():
    with open(RESULTS_PATH) as f:
        return json.load(f)


def parse_dataset():
    rows = []
    with open(DATASET_PATH) as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows


def build_correct_graph(rows):
    G = nx.DiGraph()
    all_regressor_bugs = set()
    fix_ids = set()

    for row in rows:
        fix_id = int(row["FIX_ID"])
        fix_ids.add(fix_id)
        G.add_node(fix_id)
        bug_ids_str = row["BUG_IDS"].strip()
        if bug_ids_str:
            for bid_str in bug_ids_str.split():
                bid = int(bid_str)
                all_regressor_bugs.add(bid)
                G.add_edge(bid, fix_id)

    return G, all_regressor_bugs, fix_ids


def build_filtered_graph(rows):
    G = nx.DiGraph()
    for row in rows:
        if row.get("NO_FILE_SHARED") == "True":
            continue
        fix_id = int(row["FIX_ID"])
        G.add_node(fix_id)
        bug_ids_str = row["BUG_IDS"].strip()
        if bug_ids_str:
            for bid_str in bug_ids_str.split():
                bid = int(bid_str)
                G.add_edge(bid, fix_id)
    return G


@pytest.fixture(scope="module")
def results():
    return load_results()


@pytest.fixture(scope="module")
def dataset():
    return parse_dataset()


@pytest.fixture(scope="module")
def graph_data(dataset):
    return build_correct_graph(dataset)


@pytest.fixture(scope="module")
def filt_graph(dataset):
    return build_filtered_graph(dataset)


# ===== File and Format Tests =====


class TestResultsFormat:
    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_PATH), "results.json not found"

    def test_results_is_valid_json(self):
        r = load_results()
        assert isinstance(r, dict)

    def test_required_standard_keys(self, results):
        required = [
            "total_pairs", "fixed_pairs", "unfixed_pairs",
            "unique_regressor_bugs", "graph_nodes", "graph_edges",
            "max_out_degree_bug", "max_out_degree", "top_10_regressors",
            "num_weakly_connected_components", "largest_wcc_size",
            "num_sccs_with_cycles", "has_cycles", "longest_chain_length",
            "no_shared_files_count", "no_bug_commit_count",
        ]
        for key in required:
            assert key in results, f"Missing standard key: {key}"

    def test_required_cascade_keys(self, results):
        required = [
            "orphan_regressor_count", "pure_regression_count",
            "multi_cause_regression_count", "transitive_impact_top3",
            "mean_regressor_fanout",
        ]
        for key in required:
            assert key in results, f"Missing cascade key: {key}"

    def test_required_audit_key(self, results):
        assert "audit" in results, "Missing audit key"

    def test_required_data_quality_key(self, results):
        assert "data_quality" in results, "Missing data_quality key"

    def test_required_filtered_graph_key(self, results):
        assert "filtered_graph" in results, "Missing filtered_graph key"

    def test_required_pagerank_key(self, results):
        assert "pagerank_top10" in results, "Missing pagerank_top10 key"

    def test_has_cycles_is_bool(self, results):
        assert isinstance(results["has_cycles"], bool)

    def test_top_10_format(self, results):
        top10 = results["top_10_regressors"]
        assert isinstance(top10, list)
        assert len(top10) == 10
        for entry in top10:
            assert isinstance(entry, list) and len(entry) == 2

    def test_transitive_impact_format(self, results):
        ti = results["transitive_impact_top3"]
        assert isinstance(ti, list)
        assert len(ti) == 3
        for entry in ti:
            assert isinstance(entry, list) and len(entry) == 2

    def test_mean_fanout_is_float(self, results):
        assert isinstance(results["mean_regressor_fanout"], float)

    def test_pagerank_top10_format(self, results):
        pr = results["pagerank_top10"]
        assert isinstance(pr, list)
        assert len(pr) == 10
        for entry in pr:
            assert isinstance(entry, list) and len(entry) == 2
            assert isinstance(entry[0], int)
            assert isinstance(entry[1], float)

    def test_data_quality_format(self, results):
        dq = results["data_quality"]
        assert isinstance(dq, dict)
        for key in ["self_referencing_pairs", "no_bug_with_commits",
                     "extrinsic_bug_count"]:
            assert key in dq, f"Missing data_quality.{key}"
            assert isinstance(dq[key], int)

    def test_filtered_graph_format(self, results):
        fg = results["filtered_graph"]
        assert isinstance(fg, dict)
        for key in ["nodes", "edges", "largest_wcc_size", "has_cycles",
                     "longest_chain_length", "edge_reduction_pct"]:
            assert key in fg, f"Missing filtered_graph.{key}"


# ===== Audit Tests =====


class TestAudit:
    def test_audit_structure(self, results):
        audit = results["audit"]
        for v in ["v1", "v2", "v3"]:
            assert v in audit, f"Missing audit entry for {v}"
            for field in [
                "edge_direction_correct", "multivalue_parsing_correct",
                "fix_classification_correct", "path_length_correct",
            ]:
                assert field in audit[v], f"Missing {field} in audit.{v}"
                assert isinstance(audit[v][field], bool)

    def test_v1_edge_direction_incorrect(self, results):
        assert results["audit"]["v1"]["edge_direction_correct"] is False

    def test_v1_multivalue_correct(self, results):
        assert results["audit"]["v1"]["multivalue_parsing_correct"] is True

    def test_v1_fix_classification_correct(self, results):
        assert results["audit"]["v1"]["fix_classification_correct"] is True

    def test_v1_path_length_correct(self, results):
        assert results["audit"]["v1"]["path_length_correct"] is True

    def test_v2_edge_direction_correct(self, results):
        assert results["audit"]["v2"]["edge_direction_correct"] is True

    def test_v2_multivalue_incorrect(self, results):
        assert results["audit"]["v2"]["multivalue_parsing_correct"] is False

    def test_v2_fix_classification_correct(self, results):
        assert results["audit"]["v2"]["fix_classification_correct"] is True

    def test_v2_path_length_correct(self, results):
        assert results["audit"]["v2"]["path_length_correct"] is True

    def test_v3_edge_direction_correct(self, results):
        assert results["audit"]["v3"]["edge_direction_correct"] is True

    def test_v3_multivalue_correct(self, results):
        assert results["audit"]["v3"]["multivalue_parsing_correct"] is True

    def test_v3_fix_classification_incorrect(self, results):
        assert results["audit"]["v3"]["fix_classification_correct"] is False

    def test_v3_path_length_incorrect(self, results):
        assert results["audit"]["v3"]["path_length_correct"] is False

    def test_each_analyzer_has_errors(self, results):
        for v in ["v1", "v2", "v3"]:
            vals = list(results["audit"][v].values())
            assert not all(vals), f"{v} must have at least one error"


# ===== Basic CSV Metrics =====


class TestBasicMetrics:
    def test_total_pairs(self, results, dataset):
        assert results["total_pairs"] == len(dataset)

    def test_fixed_pairs(self, results, dataset):
        expected = sum(
            1 for r in dataset if r["FIX_COMMITS_MERCURIAL"].strip()
        )
        assert results["fixed_pairs"] == expected

    def test_unfixed_pairs(self, results, dataset):
        expected = sum(
            1 for r in dataset if not r["FIX_COMMITS_MERCURIAL"].strip()
        )
        assert results["unfixed_pairs"] == expected

    def test_pairs_sum(self, results):
        assert (
            results["total_pairs"]
            == results["fixed_pairs"] + results["unfixed_pairs"]
        )

    def test_unique_regressor_bugs(self, results, dataset):
        all_bugs = set()
        for row in dataset:
            bug_ids_str = row["BUG_IDS"].strip()
            if bug_ids_str:
                for bid in bug_ids_str.split():
                    all_bugs.add(int(bid))
        assert results["unique_regressor_bugs"] == len(all_bugs)


# ===== Graph Structure Metrics =====


class TestGraphMetrics:
    def test_graph_nodes(self, results, graph_data):
        G, _, _ = graph_data
        assert results["graph_nodes"] == G.number_of_nodes()

    def test_graph_edges(self, results, graph_data):
        G, _, _ = graph_data
        assert results["graph_edges"] == G.number_of_edges()

    def test_max_out_degree(self, results, graph_data):
        G, _, _ = graph_data
        out_degs = sorted(
            [(n, G.out_degree(n)) for n in G.nodes()],
            key=lambda x: (-x[1], x[0]),
        )
        assert results["max_out_degree_bug"] == out_degs[0][0]
        assert results["max_out_degree"] == out_degs[0][1]

    def test_top_10_regressors(self, results, graph_data):
        G, _, _ = graph_data
        out_degs = sorted(
            [(n, G.out_degree(n)) for n in G.nodes()],
            key=lambda x: (-x[1], x[0]),
        )
        expected = [[n, d] for n, d in out_degs[:10]]
        assert results["top_10_regressors"] == expected


# ===== Component and Cycle Metrics =====


class TestComponentMetrics:
    def test_weakly_connected_components(self, results, graph_data):
        G, _, _ = graph_data
        expected = nx.number_weakly_connected_components(G)
        assert results["num_weakly_connected_components"] == expected

    def test_largest_wcc_size(self, results, graph_data):
        G, _, _ = graph_data
        wccs = list(nx.weakly_connected_components(G))
        assert results["largest_wcc_size"] == max(len(c) for c in wccs)

    def test_sccs_with_cycles(self, results, graph_data):
        G, _, _ = graph_data
        sccs = list(nx.strongly_connected_components(G))
        expected = sum(1 for scc in sccs if len(scc) > 1)
        assert results["num_sccs_with_cycles"] == expected

    def test_has_cycles(self, results, graph_data):
        G, _, _ = graph_data
        sccs = list(nx.strongly_connected_components(G))
        expected = any(len(scc) > 1 for scc in sccs)
        assert results["has_cycles"] == expected

    def test_longest_chain_length(self, results, graph_data):
        G, _, _ = graph_data
        C = nx.condensation(G)
        expected = nx.dag_longest_path_length(C)
        assert results["longest_chain_length"] == expected


# ===== Boolean Flag Counts =====


class TestBooleanCounts:
    def test_no_shared_files_count(self, results, dataset):
        expected = sum(
            1 for r in dataset if r.get("NO_FILE_SHARED") == "True"
        )
        assert results["no_shared_files_count"] == expected

    def test_no_bug_commit_count(self, results, dataset):
        expected = sum(1 for r in dataset if r.get("NO_BUG") == "True")
        assert results["no_bug_commit_count"] == expected


# ===== Cascade Vulnerability Metrics =====


class TestCascadeMetrics:
    def test_orphan_regressor_count(self, results, graph_data):
        _, all_regressor_bugs, fix_ids = graph_data
        expected = len(all_regressor_bugs - fix_ids)
        assert results["orphan_regressor_count"] == expected

    def test_pure_regression_count(self, results, graph_data):
        _, all_regressor_bugs, fix_ids = graph_data
        expected = len(fix_ids - all_regressor_bugs)
        assert results["pure_regression_count"] == expected

    def test_multi_cause_regression_count(self, results, dataset):
        count = 0
        for row in dataset:
            bug_ids_str = row["BUG_IDS"].strip()
            if bug_ids_str:
                if len(set(bug_ids_str.split())) > 1:
                    count += 1
        assert results["multi_cause_regression_count"] == count

    def test_transitive_impact_top3(self, results, graph_data):
        G, _, _ = graph_data
        out_degs = sorted(
            [(n, G.out_degree(n)) for n in G.nodes()],
            key=lambda x: (-x[1], x[0]),
        )
        top3 = out_degs[:3]
        expected = [[n, len(nx.descendants(G, n))] for n, _ in top3]
        assert results["transitive_impact_top3"] == expected

    def test_mean_regressor_fanout(self, results, graph_data):
        G, _, _ = graph_data
        nodes_with_out = [(n, d) for n, d in G.out_degree() if d > 0]
        expected = round(
            sum(d for _, d in nodes_with_out) / len(nodes_with_out), 2
        )
        assert results["mean_regressor_fanout"] == pytest.approx(
            expected, abs=0.005
        )


# ===== Data Quality Triage =====


class TestDataQuality:
    def test_self_referencing_pairs(self, results, dataset):
        count = 0
        for row in dataset:
            fix_id = int(row["FIX_ID"])
            bug_ids_str = row["BUG_IDS"].strip()
            if bug_ids_str:
                bug_ids = [int(b) for b in bug_ids_str.split()]
                if fix_id in bug_ids:
                    count += 1
        assert results["data_quality"]["self_referencing_pairs"] == count

    def test_no_bug_with_commits(self, results, dataset):
        count = 0
        for row in dataset:
            if (row.get("NO_BUG") == "True"
                    and row["BUG_COMMITS_MERCURIAL"].strip()):
                count += 1
        assert results["data_quality"]["no_bug_with_commits"] == count

    def test_extrinsic_bug_count(self, results, dataset):
        expected = sum(
            1 for r in dataset if r.get("NO_FILE_SHARED") == "True"
        )
        assert results["data_quality"]["extrinsic_bug_count"] == expected

    def test_extrinsic_matches_no_shared_files(self, results):
        assert (results["data_quality"]["extrinsic_bug_count"]
                == results["no_shared_files_count"])


# ===== Filtered Graph Analysis =====


class TestFilteredGraph:
    def test_filtered_nodes(self, results, filt_graph):
        assert results["filtered_graph"]["nodes"] == filt_graph.number_of_nodes()

    def test_filtered_edges(self, results, filt_graph):
        assert results["filtered_graph"]["edges"] == filt_graph.number_of_edges()

    def test_filtered_largest_wcc(self, results, filt_graph):
        if filt_graph.number_of_nodes() > 0:
            expected = max(
                len(c) for c in nx.weakly_connected_components(filt_graph)
            )
        else:
            expected = 0
        assert results["filtered_graph"]["largest_wcc_size"] == expected

    def test_filtered_has_cycles(self, results, filt_graph):
        sccs = list(nx.strongly_connected_components(filt_graph))
        expected = any(len(scc) > 1 for scc in sccs)
        assert results["filtered_graph"]["has_cycles"] == expected

    def test_filtered_longest_chain(self, results, filt_graph):
        if filt_graph.number_of_nodes() > 0:
            C = nx.condensation(filt_graph)
            expected = nx.dag_longest_path_length(C)
        else:
            expected = 0
        assert results["filtered_graph"]["longest_chain_length"] == expected

    def test_edge_reduction_pct(self, results, graph_data, filt_graph):
        G, _, _ = graph_data
        if G.number_of_edges() > 0:
            expected = round(
                (1.0 - filt_graph.number_of_edges() / G.number_of_edges())
                * 100, 2
            )
        else:
            expected = 0.0
        assert results["filtered_graph"]["edge_reduction_pct"] == pytest.approx(
            expected, abs=0.01
        )

    def test_filtered_has_fewer_edges(self, results):
        assert results["filtered_graph"]["edges"] <= results["graph_edges"]

    def test_filtered_has_fewer_or_equal_nodes(self, results):
        assert results["filtered_graph"]["nodes"] <= results["graph_nodes"]


# ===== PageRank Propagation Risk =====


class TestPageRank:
    def test_pagerank_top10_ids(self, results, graph_data):
        G, _, _ = graph_data
        pr = nx.pagerank(G)
        pr_sorted = sorted(pr.items(), key=lambda x: (-x[1], x[0]))
        expected_ids = [n for n, _ in pr_sorted[:10]]
        actual_ids = [entry[0] for entry in results["pagerank_top10"]]
        assert actual_ids == expected_ids

    def test_pagerank_top10_scores(self, results, graph_data):
        G, _, _ = graph_data
        pr = nx.pagerank(G)
        pr_sorted = sorted(pr.items(), key=lambda x: (-x[1], x[0]))
        for i, (_, expected_s) in enumerate(pr_sorted[:10]):
            assert results["pagerank_top10"][i][1] == pytest.approx(
                round(expected_s, 6), abs=1e-4
            )

    def test_pagerank_scores_descending(self, results):
        pr = results["pagerank_top10"]
        for i in range(len(pr) - 1):
            assert pr[i][1] >= pr[i + 1][1]

    def test_pagerank_scores_positive(self, results):
        for entry in results["pagerank_top10"]:
            assert entry[1] > 0


# ===== Consistency and Anti-Cheating Tests =====


class TestConsistency:
    def test_nodes_gte_regressor_count(self, results):
        assert results["graph_nodes"] >= results["unique_regressor_bugs"]

    def test_nodes_gte_total_pairs(self, results):
        assert results["graph_nodes"] >= results["total_pairs"]

    def test_orphan_plus_overlap_equals_regressors(self, results, graph_data):
        _, all_regressor_bugs, fix_ids = graph_data
        overlap = len(all_regressor_bugs & fix_ids)
        assert (
            results["orphan_regressor_count"] + overlap
            == results["unique_regressor_bugs"]
        )

    def test_pure_plus_overlap_equals_total(self, results, graph_data):
        _, all_regressor_bugs, fix_ids = graph_data
        overlap = len(all_regressor_bugs & fix_ids)
        assert (
            results["pure_regression_count"] + overlap
            == results["total_pairs"]
        )

    def test_top_10_sorted(self, results):
        top10 = results["top_10_regressors"]
        for i in range(len(top10) - 1):
            assert top10[i][1] >= top10[i + 1][1]
            if top10[i][1] == top10[i + 1][1]:
                assert top10[i][0] < top10[i + 1][0]

    def test_results_differ_from_v1(self, results):
        """Correct results must differ from v1 on top_10 (reversed edges)"""
        v1_path = "/app/pipeline/output_v1.json"
        if os.path.exists(v1_path):
            with open(v1_path) as f:
                v1 = json.load(f)
            assert results["top_10_regressors"] != v1["top_10_regressors"]

    def test_results_differ_from_v2(self, results):
        """Correct results must differ from v2 on graph_edges (missing edges)"""
        v2_path = "/app/pipeline/output_v2.json"
        if os.path.exists(v2_path):
            with open(v2_path) as f:
                v2 = json.load(f)
            assert results["graph_edges"] != v2["graph_edges"]

    def test_results_differ_from_v3(self, results):
        """Correct results must differ from v3 on fixed_pairs (wrong column)"""
        v3_path = "/app/pipeline/output_v3.json"
        if os.path.exists(v3_path):
            with open(v3_path) as f:
                v3 = json.load(f)
            assert results["fixed_pairs"] != v3["fixed_pairs"]

    def test_has_cycles_consistent_with_scc(self, results):
        if results["has_cycles"]:
            assert results["num_sccs_with_cycles"] > 0
        else:
            assert results["num_sccs_with_cycles"] == 0

    def test_largest_wcc_leq_nodes(self, results):
        assert results["largest_wcc_size"] <= results["graph_nodes"]
