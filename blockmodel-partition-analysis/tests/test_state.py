"""
Test suite for partition evaluation pipeline audit.

Independently computes reference values and compares against agent output.

"""
import json
import os
import math
import pytest
import numpy as np
from scipy.optimize import linear_sum_assignment

RESULTS_PATH = "/app/results.json"
GRAPH_PATH = "/app/data/network.tsv"
TRUTH_PATH = "/app/data/ground_truth.tsv"
DETECTIONS_DIR = "/app/data/detections"
CANDIDATE_IDS = ["A", "B", "C", "D", "E", "F"]

# --- Reference implementation ---


def load_graph(path):
    """Load directed graph from TSV edge list (source, destination, weight)."""
    edges = []
    with open(path) as f:
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) >= 3:
                edges.append((int(parts[0]), int(parts[1]), int(parts[2])))
    return edges


def load_partition(path):
    """Load partition from TSV (node, block). Re-index to consecutive 0-based labels."""
    data = []
    with open(path) as f:
        for line in f:
            parts = line.strip().split('\t')
            data.append((int(parts[0]) - 1, int(parts[1])))
    N = max(n for n, _ in data) + 1
    raw_labels = [0] * N
    for n, b in data:
        raw_labels[n] = b
    unique_labels = sorted(set(raw_labels))
    label_map = {l: i for i, l in enumerate(unique_labels)}
    partition = np.array([label_map[raw_labels[i]] for i in range(N)])
    return partition


def compute_interblock_edge_count(edges, partition):
    """Compute inter-block edge count matrix M[r,s] for directed graph."""
    B = int(partition.max()) + 1
    M = np.zeros((B, B), dtype=int)
    for src, dst, w in edges:
        r = partition[src - 1]
        s = partition[dst - 1]
        M[r, s] += w
    return M


def compute_description_length(edges, partition, N):
    """Compute DC-SBM description length (Peixoto 2012)."""
    M = compute_interblock_edge_count(edges, partition)
    B = M.shape[0]
    E = sum(w for _, _, w in edges)

    d_out = M.sum(axis=1).astype(float)
    d_in = M.sum(axis=0).astype(float)

    x = float(B ** 2) / float(E)
    S_model = E * ((1.0 + x) * math.log(1.0 + x) - x * math.log(x)) + N * math.log(B)

    nz = M.nonzero()
    M_vals = M[nz[0], nz[1]].astype(float)
    d_out_vals = d_out[nz[0]]
    d_in_vals = d_in[nz[1]]

    S_data = -float(np.sum(M_vals * np.log(M_vals / (d_out_vals * d_in_vals))))

    return S_model + S_data


def compute_accuracy(true_part, pred_part):
    """Accuracy with optimal label matching via Hungarian algorithm."""
    B_t = int(true_part.max()) + 1
    B_p = int(pred_part.max()) + 1

    C = np.zeros((B_t, B_p), dtype=int)
    for i in range(len(true_part)):
        C[true_part[i], pred_part[i]] += 1

    row_ind, col_ind = linear_sum_assignment(-C)
    correct = C[row_ind, col_ind].sum()
    return float(correct) / float(len(true_part))


def compute_ari(true_part, pred_part):
    """Adjusted Rand Index from contingency table."""
    B_t = int(true_part.max()) + 1
    B_p = int(pred_part.max()) + 1
    N = len(true_part)

    C = np.zeros((B_t, B_p), dtype=float)
    for i in range(N):
        C[true_part[i], pred_part[i]] += 1.0

    a = C.sum(axis=1)
    b = C.sum(axis=0)

    def comb2(x):
        return x * (x - 1.0) / 2.0

    sum_comb_nij = 0.0
    for i in range(B_t):
        for j in range(B_p):
            sum_comb_nij += comb2(C[i, j])

    sum_comb_a = sum(comb2(ai) for ai in a)
    sum_comb_b = sum(comb2(bj) for bj in b)
    comb_N = comb2(float(N))

    expected = sum_comb_a * sum_comb_b / comb_N
    max_index = (sum_comb_a + sum_comb_b) / 2.0

    if max_index == expected:
        return 1.0
    return (sum_comb_nij - expected) / (max_index - expected)


def compute_nmi(true_part, pred_part):
    """Normalized Mutual Information (arithmetic mean normalization)."""
    N = len(true_part)
    B_t = int(true_part.max()) + 1
    B_p = int(pred_part.max()) + 1

    C = np.zeros((B_t, B_p), dtype=float)
    for i in range(N):
        C[true_part[i], pred_part[i]] += 1.0

    joint = C / float(N)
    p_t = joint.sum(axis=1)
    p_p = joint.sum(axis=0)

    H_t = 0.0
    for p in p_t:
        if p > 0:
            H_t -= p * math.log(p)

    H_p = 0.0
    for p in p_p:
        if p > 0:
            H_p -= p * math.log(p)

    MI = 0.0
    for i in range(B_t):
        for j in range(B_p):
            if joint[i, j] > 0:
                MI += joint[i, j] * math.log(joint[i, j] / (p_t[i] * p_p[j]))

    if H_t + H_p == 0:
        return 1.0
    return 2.0 * MI / (H_t + H_p)


# --- Fixtures ---


@pytest.fixture(scope="module")
def reference_data():
    """Compute all reference values from input data."""
    edges = load_graph(GRAPH_PATH)
    truth = load_partition(TRUTH_PATH)
    N = len(truth)

    candidates = {}
    for cid in CANDIDATE_IDS:
        path = os.path.join(DETECTIONS_DIR, "result_{}.tsv".format(cid))
        candidates[cid] = load_partition(path)

    ref_desc_lengths = {}
    ref_desc_lengths["truth"] = compute_description_length(edges, truth, N)
    for k, part in candidates.items():
        ref_desc_lengths[k] = compute_description_length(edges, part, N)

    ref_metrics = {}
    for k, part in candidates.items():
        ref_metrics[k] = {
            "accuracy": compute_accuracy(truth, part),
            "ari": compute_ari(truth, part),
            "nmi": compute_nmi(truth, part),
        }

    cand_lengths = {k: v for k, v in ref_desc_lengths.items() if k != "truth"}
    ref_best = min(cand_lengths, key=cand_lengths.get)
    ref_ranking = sorted(cand_lengths.keys(), key=lambda k: cand_lengths[k])

    return {
        "desc_lengths": ref_desc_lengths,
        "metrics": ref_metrics,
        "best": ref_best,
        "ranking": ref_ranking,
    }


@pytest.fixture(scope="module")
def agent_results():
    """Load agent output from results.json."""
    with open(RESULTS_PATH) as f:
        return json.load(f)


# --- Tests ---


class TestResultsStructure:
    """Verify the output JSON has the correct structure."""

    def test_results_file_exists(self):
        assert os.path.isfile(RESULTS_PATH), "results.json not found at /app/results.json"

    def test_top_level_keys(self, agent_results):
        for key in ["description_lengths", "best_partition", "ranking", "comparison_metrics"]:
            assert key in agent_results, "Missing top-level key: {}".format(key)

    def test_desc_length_keys(self, agent_results):
        dl = agent_results["description_lengths"]
        assert "truth" in dl, "Missing 'truth' key in description_lengths"
        for cid in CANDIDATE_IDS:
            assert cid in dl, "Missing key '{}' in description_lengths".format(cid)

    def test_metrics_keys(self, agent_results):
        metrics = agent_results["comparison_metrics"]
        for cid in CANDIDATE_IDS:
            assert cid in metrics, "Missing key '{}' in comparison_metrics".format(cid)
            for mkey in ["accuracy", "ari", "nmi"]:
                assert mkey in metrics[cid], \
                    "Missing '{}' in comparison_metrics['{}']".format(mkey, cid)

    def test_ranking_length(self, agent_results):
        ranking = agent_results["ranking"]
        assert len(ranking) == len(CANDIDATE_IDS), \
            "ranking should have {} entries, got {}".format(len(CANDIDATE_IDS), len(ranking))


class TestDescriptionLengths:
    """Verify description length computations match reference."""

    def test_truth_desc_length(self, agent_results, reference_data):
        ref = reference_data["desc_lengths"]["truth"]
        agent = agent_results["description_lengths"]["truth"]
        rel_err = abs(agent - ref) / abs(ref)
        assert rel_err < 0.001, \
            "Truth description length: expected {:.4f}, got {:.4f} (rel err {:.6f})".format(
                ref, agent, rel_err)

    @pytest.mark.parametrize("cand_id", CANDIDATE_IDS)
    def test_candidate_desc_length(self, cand_id, agent_results, reference_data):
        ref = reference_data["desc_lengths"][cand_id]
        agent = agent_results["description_lengths"][cand_id]
        rel_err = abs(agent - ref) / abs(ref)
        assert rel_err < 0.001, \
            "Partition {} description length: expected {:.4f}, got {:.4f} (rel err {:.6f})".format(
                cand_id, ref, agent, rel_err)


class TestRanking:
    """Verify ranking and best partition identification."""

    def test_best_partition(self, agent_results, reference_data):
        ref_best = reference_data["best"]
        agent_best = agent_results["best_partition"]
        assert agent_best == ref_best, \
            "Best partition: expected {}, got {}".format(ref_best, agent_best)

    def test_ranking_order(self, agent_results, reference_data):
        ref_ranking = reference_data["ranking"]
        agent_ranking = agent_results["ranking"]
        assert agent_ranking == ref_ranking, \
            "Ranking: expected {}, got {}".format(ref_ranking, agent_ranking)


class TestEvaluationMetrics:
    """Verify partition evaluation metrics match reference."""

    @pytest.mark.parametrize("cand_id", CANDIDATE_IDS)
    def test_accuracy(self, cand_id, agent_results, reference_data):
        ref = reference_data["metrics"][cand_id]["accuracy"]
        agent = agent_results["comparison_metrics"][cand_id]["accuracy"]
        assert abs(agent - ref) < 0.005, \
            "Partition {} accuracy: expected {:.4f}, got {:.4f}".format(cand_id, ref, agent)

    @pytest.mark.parametrize("cand_id", CANDIDATE_IDS)
    def test_ari(self, cand_id, agent_results, reference_data):
        ref = reference_data["metrics"][cand_id]["ari"]
        agent = agent_results["comparison_metrics"][cand_id]["ari"]
        assert abs(agent - ref) < 0.005, \
            "Partition {} ARI: expected {:.4f}, got {:.4f}".format(cand_id, ref, agent)

    @pytest.mark.parametrize("cand_id", CANDIDATE_IDS)
    def test_nmi(self, cand_id, agent_results, reference_data):
        ref = reference_data["metrics"][cand_id]["nmi"]
        agent = agent_results["comparison_metrics"][cand_id]["nmi"]
        assert abs(agent - ref) < 0.005, \
            "Partition {} NMI: expected {:.4f}, got {:.4f}".format(cand_id, ref, agent)


class TestMetricCoherence:
    """Verify that metrics are coherent (better partitions have better scores)."""

    def test_near_perfect_beats_random_accuracy(self, agent_results):
        m = agent_results["comparison_metrics"]
        assert m["F"]["accuracy"] > m["A"]["accuracy"], \
            "Near-perfect partition (F) should have higher accuracy than random (A)"

    def test_near_perfect_beats_noisy_ari(self, agent_results):
        m = agent_results["comparison_metrics"]
        assert m["F"]["ari"] > m["D"]["ari"], \
            "Near-perfect partition (F) should have higher ARI than noisy (D)"

    def test_good_beats_random_nmi(self, agent_results):
        m = agent_results["comparison_metrics"]
        assert m["E"]["nmi"] > m["A"]["nmi"], \
            "Good partition (E) should have higher NMI than random (A)"

    def test_single_block_low_nmi(self, agent_results):
        m = agent_results["comparison_metrics"]
        assert m["B"]["nmi"] < 0.01, \
            "Single-block partition (B) should have near-zero NMI"

    def test_single_block_low_ari(self, agent_results):
        m = agent_results["comparison_metrics"]
        assert m["B"]["ari"] < 0.01, \
            "Single-block partition (B) should have near-zero ARI"

    def test_truth_desc_length_lower_than_random(self, agent_results):
        dl = agent_results["description_lengths"]
        assert dl["truth"] < dl["A"], \
            "Truth partition should have lower description length than random (A)"

    def test_truth_desc_length_lower_than_single_block(self, agent_results):
        dl = agent_results["description_lengths"]
        assert dl["truth"] < dl["B"], \
            "Truth partition should have lower description length than single-block (B)"
