
import json
import subprocess
import os
import math
import numpy as np
import yaml
from collections import Counter

# ---------------------------------------------------------------------------
# Reference implementation of all 9 metrics (RecBole-compatible semantics)
# ---------------------------------------------------------------------------


def _pos_index(ranked_items, relevant_set, k):
    items = ranked_items[:k]
    return np.array([1.0 if it in relevant_set else 0.0 for it in items])


def _ref_hit(pi):
    return 1.0 if pi.sum() > 0 else 0.0


def _ref_recall(pi, pos_len):
    if pos_len == 0:
        return 0.0
    return float(pi.sum()) / pos_len


def _ref_precision(pi):
    k = len(pi)
    if k == 0:
        return 0.0
    return float(pi.sum()) / k


def _ref_mrr(pi):
    for i in range(len(pi)):
        if pi[i] > 0:
            return 1.0 / (i + 1)
    return 0.0


def _ref_ndcg(pi, pos_len):
    k = len(pi)
    if pos_len == 0 or k == 0:
        return 0.0
    ranks = np.arange(1, k + 1, dtype=np.float64)
    dcg = float(np.sum(pi / np.log2(ranks + 1)))
    idcg_len = min(int(pos_len), k)
    ideal_ranks = np.arange(1, idcg_len + 1, dtype=np.float64)
    idcg = float(np.sum(1.0 / np.log2(ideal_ranks + 1)))
    if idcg == 0:
        return 0.0
    return dcg / idcg


def _ref_map(pi, pos_len):
    k = len(pi)
    if pos_len == 0 or k == 0:
        return 0.0
    cumsum = np.cumsum(pi)
    prec_at = cumsum / np.arange(1, k + 1, dtype=np.float64)
    sum_prec = float(np.sum(prec_at * pi))
    actual_len = min(int(pos_len), k)
    if actual_len == 0:
        return 0.0
    return sum_prec / actual_len


def _ref_item_coverage(all_items, k, num_items):
    s = set()
    for items in all_items:
        s.update(items[:k])
    return len(s) / num_items


def _ref_gini(all_items, k, num_items):
    flat = []
    for items in all_items:
        flat.extend(items[:k])
    if not flat:
        return 0.0
    cnt = Counter(flat)
    sc = np.array(sorted(cnt.values()), dtype=np.float64)
    nr = len(sc)
    total = len(flat)
    idx = np.arange(num_items - nr + 1, num_items + 1, dtype=np.float64)
    g = float(np.sum((2 * idx - num_items - 1) * sc)) / total
    return g / num_items


def _ref_entropy(all_items, k):
    flat = []
    for items in all_items:
        flat.extend(items[:k])
    if not flat:
        return 0.0
    cnt = Counter(flat)
    total = len(flat)
    if len(cnt) == 0:
        return 0.0
    ent = 0.0
    for c in cnt.values():
        p = c / total
        ent += -p * math.log(p)
    return ent / len(cnt)


def _compute_expected(ranked_data, gt_data, config):
    topks = config["topk"]
    mnames = [m.lower() for m in config["metrics"]]
    num_items = config.get("num_items", 0)

    gt_map = {}
    for u in gt_data["users"]:
        gt_map[u["user_id"]] = set(u["relevant_items"])

    all_users = [(u["user_id"], u["ranked_items"]) for u in ranked_data["users"]]
    results = {}

    for k in topks:
        pu = {m: [] for m in ["recall", "precision", "hit", "mrr", "ndcg", "map"]}
        item_lists = []

        for uid, ritems in all_users:
            rel = gt_map.get(uid, set())
            pl = len(rel)
            pi = _pos_index(ritems, rel, k)
            item_lists.append(ritems)

            if pl > 0:
                pu["recall"].append(_ref_recall(pi, pl))
                pu["precision"].append(_ref_precision(pi))
                pu["hit"].append(_ref_hit(pi))
                pu["mrr"].append(_ref_mrr(pi))
                pu["ndcg"].append(_ref_ndcg(pi, pl))
                pu["map"].append(_ref_map(pi, pl))

        for m in ["recall", "precision", "hit", "mrr", "ndcg", "map"]:
            if m in mnames and pu[m]:
                results[f"{m}@{k}"] = round(float(np.mean(pu[m])), 4)

        if "itemcoverage" in mnames:
            results[f"itemcoverage@{k}"] = round(_ref_item_coverage(item_lists, k, num_items), 4)
        if "giniindex" in mnames:
            results[f"giniindex@{k}"] = round(_ref_gini(item_lists, k, num_items), 4)
        if "shannonentropy" in mnames:
            results[f"shannonentropy@{k}"] = round(_ref_entropy(item_lists, k), 4)

    return results


# ---------------------------------------------------------------------------
# Reference score-to-ranking conversion
# ---------------------------------------------------------------------------


def _ref_convert_scores(scores_data, relevance_data, config):
    """Reference implementation of correct score-to-ranked-list conversion."""
    scores = np.array(scores_data, dtype=np.float64)
    relevance = np.array(relevance_data, dtype=np.float64)
    n_users, n_items = scores.shape

    ranked_users = []
    gt_users = []
    for i in range(n_users):
        sorted_indices = np.argsort(-scores[i])
        ranked_items = (sorted_indices + 1).tolist()
        ranked_users.append({"user_id": i, "ranked_items": ranked_items})

        rel_indices = np.where(relevance[i] > 0)[0]
        relevant_items = (rel_indices + 1).tolist()
        gt_users.append({"user_id": i, "relevant_items": relevant_items})

    ranked = {"users": ranked_users}
    gt = {"users": gt_users}

    topk = config["topk"]
    if isinstance(topk, int):
        topk = [topk]

    eval_config = {
        "topk": topk,
        "metrics": config.get("metrics", []),
        "num_items": config.get("num_items", n_items)
    }

    return ranked, gt, eval_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_eval(input_dir, output_file):
    r = subprocess.run(
        ["python3", "/app/eval_tool.py", input_dir, output_file],
        capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, f"eval_tool.py failed (rc={r.returncode}):\n{r.stderr}"
    with open(output_file) as f:
        return json.load(f)


def _run_converter(scores_dir, output_dir):
    r = subprocess.run(
        ["python3", "/app/score_converter.py", scores_dir, output_dir],
        capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, f"score_converter.py failed (rc={r.returncode}):\n{r.stderr}"


def _run_pipeline(scores_dir, processed_dir, output_file):
    os.makedirs(processed_dir, exist_ok=True)
    _run_converter(scores_dir, processed_dir)
    return _run_eval(processed_dir, output_file)


def _assert_match(actual, expected, tol=1e-3):
    for key, ev in expected.items():
        assert key in actual, f"Missing key: {key}. Got keys: {sorted(actual.keys())}"
        av = actual[key]
        assert abs(av - ev) < tol, (
            f"{key}: expected {ev:.6f}, got {av:.6f} (diff={abs(av - ev):.6f})"
        )


def _load_case(d):
    with open(os.path.join(d, "ranked_lists.json")) as f:
        ranked = json.load(f)
    with open(os.path.join(d, "ground_truth.json")) as f:
        gt = json.load(f)
    with open(os.path.join(d, "config.json")) as f:
        cfg = json.load(f)
    return ranked, gt, cfg


def _write_case(d, ranked, gt, cfg):
    os.makedirs(d, exist_ok=True)
    for name, obj in [("ranked_lists.json", ranked),
                       ("ground_truth.json", gt),
                       ("config.json", cfg)]:
        with open(os.path.join(d, name), "w") as f:
            json.dump(obj, f)


def _load_score_case(d):
    with open(os.path.join(d, "scores.json")) as f:
        scores = json.load(f)
    with open(os.path.join(d, "relevance.json")) as f:
        relevance = json.load(f)
    with open(os.path.join(d, "eval_config.yaml")) as f:
        config = yaml.safe_load(f)
    return scores, relevance, config


# ---------------------------------------------------------------------------
# Tests on provided JSON scenarios (eval_tool.py only)
# ---------------------------------------------------------------------------


class TestProvidedScenarios:
    def test_scenario1(self):
        os.makedirs("/app/results", exist_ok=True)
        actual = _run_eval("/app/data/scenario1", "/app/results/scenario1.json")
        ranked, gt, cfg = _load_case("/app/data/scenario1")
        expected = _compute_expected(ranked, gt, cfg)
        _assert_match(actual, expected)

    def test_scenario2(self):
        os.makedirs("/app/results", exist_ok=True)
        actual = _run_eval("/app/data/scenario2", "/app/results/scenario2.json")
        ranked, gt, cfg = _load_case("/app/data/scenario2")
        expected = _compute_expected(ranked, gt, cfg)
        _assert_match(actual, expected)

    def test_scenario3(self):
        os.makedirs("/app/results", exist_ok=True)
        actual = _run_eval("/app/data/scenario3", "/app/results/scenario3.json")
        ranked, gt, cfg = _load_case("/app/data/scenario3")
        expected = _compute_expected(ranked, gt, cfg)
        _assert_match(actual, expected)


# ---------------------------------------------------------------------------
# Pipeline tests (score_converter.py → eval_tool.py)
# ---------------------------------------------------------------------------


class TestPipelineScenarios:
    def test_scenario4_pipeline(self):
        """Full pipeline on score matrix scenario with list topk."""
        scores, relevance, config = _load_score_case("/app/data/scenario4")
        ranked, gt, eval_cfg = _ref_convert_scores(scores, relevance, config)
        expected = _compute_expected(ranked, gt, eval_cfg)

        actual = _run_pipeline(
            "/app/data/scenario4",
            "/tmp/tb_pipeline_s4",
            "/tmp/tb_pipeline_s4_out.json"
        )
        _assert_match(actual, expected)

    def test_scenario5_pipeline(self):
        """Full pipeline on score matrix scenario with scalar topk, empty users, and
        num_items larger than score matrix width."""
        scores, relevance, config = _load_score_case("/app/data/scenario5")
        ranked, gt, eval_cfg = _ref_convert_scores(scores, relevance, config)
        expected = _compute_expected(ranked, gt, eval_cfg)

        actual = _run_pipeline(
            "/app/data/scenario5",
            "/tmp/tb_pipeline_s5",
            "/tmp/tb_pipeline_s5_out.json"
        )
        _assert_match(actual, expected)

    def test_scenario4_ranking_order(self):
        """Verify the converter produces descending-score ranking."""
        scores, relevance, config = _load_score_case("/app/data/scenario4")

        _run_converter("/app/data/scenario4", "/tmp/tb_s4_conv")
        with open("/tmp/tb_s4_conv/ranked_lists.json") as f:
            converted = json.load(f)

        scores_np = np.array(scores, dtype=np.float64)
        for user in converted["users"]:
            uid = user["user_id"]
            ranked_items = user["ranked_items"]
            # The first ranked item should have the highest score
            first_item_idx = ranked_items[0] - 1  # convert to 0-based
            last_item_idx = ranked_items[-1] - 1
            assert scores_np[uid, first_item_idx] >= scores_np[uid, last_item_idx], (
                f"User {uid}: first ranked item (score={scores_np[uid, first_item_idx]:.2f}) "
                f"should have higher score than last (score={scores_np[uid, last_item_idx]:.2f})"
            )

    def test_scenario5_scalar_topk_handling(self):
        """Score converter must handle scalar topk in YAML."""
        _run_converter("/app/data/scenario5", "/tmp/tb_s5_topk")
        with open("/tmp/tb_s5_topk/config.json") as f:
            cfg = json.load(f)
        assert isinstance(cfg["topk"], list), (
            f"topk should be a list, got {type(cfg['topk']).__name__}: {cfg['topk']}"
        )

    def test_scenario5_num_items_from_config(self):
        """Score converter must use num_items from YAML config, not score matrix width."""
        _run_converter("/app/data/scenario5", "/tmp/tb_s5_numitems")
        with open("/tmp/tb_s5_numitems/config.json") as f:
            cfg = json.load(f)
        # YAML config says num_items: 15, score matrix is 6x12
        assert cfg["num_items"] == 15, (
            f"num_items should be 15 (from config), got {cfg['num_items']} "
            f"(likely using score matrix width instead)"
        )

    def test_converter_item_ids_are_1_based(self):
        """Converted item IDs must be 1-based integers."""
        _run_converter("/app/data/scenario4", "/tmp/tb_s4_ids")
        with open("/tmp/tb_s4_ids/ranked_lists.json") as f:
            ranked = json.load(f)
        for user in ranked["users"]:
            assert all(x >= 1 for x in user["ranked_items"]), (
                f"User {user['user_id']}: found 0-based item IDs in ranked_items"
            )
            assert 0 not in user["ranked_items"], (
                f"User {user['user_id']}: item ID 0 found (should be 1-based)"
            )


# ---------------------------------------------------------------------------
# Score conversion correctness on synthetic data
# ---------------------------------------------------------------------------


class TestScoreConversionCorrectness:
    def test_simple_descending_sort(self):
        """Basic test: highest score should be first in ranked list."""
        d = "/tmp/tb_sort_test"
        os.makedirs(d, exist_ok=True)
        scores = [[0.1, 0.5, 0.9, 0.3]]
        relevance = [[0, 1, 1, 0]]
        config = {"topk": [2], "metrics": ["recall"], "num_items": 4}
        with open(os.path.join(d, "scores.json"), "w") as f:
            json.dump(scores, f)
        with open(os.path.join(d, "relevance.json"), "w") as f:
            json.dump(relevance, f)
        with open(os.path.join(d, "eval_config.yaml"), "w") as f:
            yaml.dump(config, f)

        _run_converter(d, "/tmp/tb_sort_out")
        with open("/tmp/tb_sort_out/ranked_lists.json") as f:
            ranked = json.load(f)

        # Item 3 (1-based) has score 0.9, should be first
        assert ranked["users"][0]["ranked_items"][0] == 3, (
            f"Highest-scored item (3) should be first, got {ranked['users'][0]['ranked_items'][0]}"
        )

    def test_pipeline_small_synthetic(self):
        """End-to-end pipeline on minimal synthetic data."""
        d = "/tmp/tb_synth"
        os.makedirs(d, exist_ok=True)
        scores = [[0.9, 0.1, 0.5], [0.3, 0.7, 0.6]]
        relevance = [[1, 0, 1], [0, 1, 0]]
        config = {"topk": [2], "metrics": ["recall", "ndcg", "mrr"], "num_items": 3}

        with open(os.path.join(d, "scores.json"), "w") as f:
            json.dump(scores, f)
        with open(os.path.join(d, "relevance.json"), "w") as f:
            json.dump(relevance, f)
        with open(os.path.join(d, "eval_config.yaml"), "w") as f:
            yaml.dump(config, f)

        ranked, gt, eval_cfg = _ref_convert_scores(scores, relevance, config)
        expected = _compute_expected(ranked, gt, eval_cfg)

        actual = _run_pipeline(d, "/tmp/tb_synth_proc", "/tmp/tb_synth_out.json")
        _assert_match(actual, expected)


# ---------------------------------------------------------------------------
# NDCG-specific tests
# ---------------------------------------------------------------------------


class TestNDCGSemantics:
    def test_ndcg_perfect_topk_with_excess_relevant(self):
        """When all top-K are relevant but user has more relevant items, NDCG must be 1.0."""
        d = "/tmp/tb_ndcg_cap"
        ranked = {"users": [{"user_id": 0, "ranked_items": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]}]}
        gt = {"users": [{"user_id": 0, "relevant_items": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]}]}
        cfg = {"topk": [5], "metrics": ["ndcg"], "num_items": 15}
        _write_case(d, ranked, gt, cfg)
        actual = _run_eval(d, "/tmp/tb_ndcg_cap_out.json")
        assert abs(actual["ndcg@5"] - 1.0) < 1e-3, (
            f"NDCG@5 should be 1.0 when top-5 is perfect (pos_len=12 > K=5), got {actual['ndcg@5']}"
        )

    def test_ndcg_scattered_hits(self):
        d = "/tmp/tb_ndcg_scatter"
        ranked = {"users": [{"user_id": 0, "ranked_items": [1, 99, 2, 98, 3, 97, 96, 95, 94, 93]}]}
        gt = {"users": [{"user_id": 0, "relevant_items": [1, 2, 3]}]}
        cfg = {"topk": [5, 10], "metrics": ["ndcg"], "num_items": 100}
        _write_case(d, ranked, gt, cfg)
        actual = _run_eval(d, "/tmp/tb_ndcg_scatter_out.json")
        expected = _compute_expected(ranked, gt, cfg)
        _assert_match(actual, expected)

    def test_ndcg_single_relevant_at_end(self):
        d = "/tmp/tb_ndcg_end"
        ranked = {"users": [{"user_id": 0, "ranked_items": [2, 3, 4, 5, 6, 7, 8, 9, 10, 1]}]}
        gt = {"users": [{"user_id": 0, "relevant_items": [1]}]}
        cfg = {"topk": [5, 10], "metrics": ["ndcg"], "num_items": 10}
        _write_case(d, ranked, gt, cfg)
        actual = _run_eval(d, "/tmp/tb_ndcg_end_out.json")
        assert abs(actual["ndcg@5"] - 0.0) < 1e-3
        exp_val = 1.0 / math.log2(11)
        assert abs(actual["ndcg@10"] - round(exp_val, 4)) < 1e-3

    def test_ndcg_various_poslen_vs_k(self):
        """Test NDCG with pos_len both less than and greater than K."""
        d = "/tmp/tb_ndcg_var"
        ranked = {"users": [
            {"user_id": 0, "ranked_items": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]},
            {"user_id": 1, "ranked_items": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]},
        ]}
        gt = {"users": [
            {"user_id": 0, "relevant_items": [1, 2, 3, 4, 5, 6, 7, 8]},
            {"user_id": 1, "relevant_items": [1]},
        ]}
        cfg = {"topk": [3, 5, 10], "metrics": ["ndcg"], "num_items": 10}
        _write_case(d, ranked, gt, cfg)
        actual = _run_eval(d, "/tmp/tb_ndcg_var_out.json")
        expected = _compute_expected(ranked, gt, cfg)
        _assert_match(actual, expected)
        assert actual["ndcg@3"] > 0.8, f"NDCG@3 should be high, got {actual['ndcg@3']}"


# ---------------------------------------------------------------------------
# MAP-specific tests
# ---------------------------------------------------------------------------


class TestMAPSemantics:
    def test_map_normalization_by_min_poslen_k(self):
        """AP should normalize by min(pos_len, K), not K."""
        d = "/tmp/tb_map_norm"
        ranked = {"users": [{"user_id": 0, "ranked_items": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]}]}
        gt = {"users": [{"user_id": 0, "relevant_items": [1, 2]}]}
        cfg = {"topk": [10], "metrics": ["map"], "num_items": 10}
        _write_case(d, ranked, gt, cfg)
        actual = _run_eval(d, "/tmp/tb_map_norm_out.json")
        assert abs(actual["map@10"] - 1.0) < 1e-3, (
            f"MAP@10 should be 1.0 (normalize by min(2,10)=2), got {actual['map@10']}"
        )

    def test_map_excess_relevant(self):
        """When pos_len > K, normalization uses K."""
        d = "/tmp/tb_map_excess"
        ranked = {"users": [{"user_id": 0, "ranked_items": [1, 2, 3, 4, 5]}]}
        gt = {"users": [{"user_id": 0, "relevant_items": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]}]}
        cfg = {"topk": [5], "metrics": ["map"], "num_items": 10}
        _write_case(d, ranked, gt, cfg)
        actual = _run_eval(d, "/tmp/tb_map_excess_out.json")
        assert abs(actual["map@5"] - 1.0) < 1e-3

    def test_map_partial_hits(self):
        d = "/tmp/tb_map_partial"
        ranked = {"users": [
            {"user_id": 0, "ranked_items": [1, 50, 2, 51, 3, 52, 53, 54, 55, 56]},
            {"user_id": 1, "ranked_items": [10, 11, 12, 13, 14, 15, 16, 17, 18, 19]},
        ]}
        gt = {"users": [
            {"user_id": 0, "relevant_items": [1, 2, 3]},
            {"user_id": 1, "relevant_items": [10]},
        ]}
        cfg = {"topk": [5, 10], "metrics": ["map"], "num_items": 60}
        _write_case(d, ranked, gt, cfg)
        actual = _run_eval(d, "/tmp/tb_map_partial_out.json")
        expected = _compute_expected(ranked, gt, cfg)
        _assert_match(actual, expected)


# ---------------------------------------------------------------------------
# MRR-specific tests
# ---------------------------------------------------------------------------


class TestMRRSemantics:
    def test_mrr_first_hit_only(self):
        """MRR uses only the first relevant item's position."""
        d = "/tmp/tb_mrr_first"
        ranked = {"users": [
            {"user_id": 0, "ranked_items": [10, 20, 1, 2, 3, 4, 5, 6, 7, 8]},
        ]}
        gt = {"users": [{"user_id": 0, "relevant_items": [1, 2, 3]}]}
        cfg = {"topk": [10], "metrics": ["mrr"], "num_items": 20}
        _write_case(d, ranked, gt, cfg)
        actual = _run_eval(d, "/tmp/tb_mrr_first_out.json")
        assert abs(actual["mrr@10"] - round(1.0 / 3, 4)) < 1e-3

    def test_mrr_no_hit_in_topk(self):
        d = "/tmp/tb_mrr_nohit"
        ranked = {"users": [{"user_id": 0, "ranked_items": [10, 20, 30, 40, 50]}]}
        gt = {"users": [{"user_id": 0, "relevant_items": [1]}]}
        cfg = {"topk": [5], "metrics": ["mrr"], "num_items": 50}
        _write_case(d, ranked, gt, cfg)
        actual = _run_eval(d, "/tmp/tb_mrr_nohit_out.json")
        assert abs(actual["mrr@5"] - 0.0) < 1e-3

    def test_mrr_multiple_relevant_items(self):
        """MRR must report 1/(position of FIRST hit), not average of all reciprocal ranks."""
        d = "/tmp/tb_mrr_multi"
        ranked = {"users": [
            {"user_id": 0, "ranked_items": [90, 91, 1, 2, 3, 4, 5, 92, 93, 94]},
        ]}
        gt = {"users": [{"user_id": 0, "relevant_items": [1, 2, 3, 4, 5]}]}
        cfg = {"topk": [10], "metrics": ["mrr"], "num_items": 100}
        _write_case(d, ranked, gt, cfg)
        actual = _run_eval(d, "/tmp/tb_mrr_multi_out.json")
        assert abs(actual["mrr@10"] - round(1.0 / 3, 4)) < 1e-3, (
            f"MRR should be 1/3 ≈ 0.3333 (first hit at pos 3), got {actual['mrr@10']}"
        )


# ---------------------------------------------------------------------------
# Diversity metrics tests
# ---------------------------------------------------------------------------


class TestDiversityMetrics:
    def test_gini_with_unrecommended_items(self):
        """Gini must account for items that are never recommended (using full catalog size)."""
        d = "/tmp/tb_gini_unr"
        ranked = {"users": [
            {"user_id": 0, "ranked_items": [1, 2, 3, 4, 5]},
            {"user_id": 1, "ranked_items": [1, 2, 3, 4, 5]},
        ]}
        gt = {"users": [
            {"user_id": 0, "relevant_items": [1]},
            {"user_id": 1, "relevant_items": [2]},
        ]}
        cfg = {"topk": [3, 5], "metrics": ["giniindex", "itemcoverage"], "num_items": 20}
        _write_case(d, ranked, gt, cfg)
        actual = _run_eval(d, "/tmp/tb_gini_unr_out.json")
        expected = _compute_expected(ranked, gt, cfg)
        _assert_match(actual, expected)
        assert abs(actual["itemcoverage@3"] - 0.15) < 1e-3

    def test_gini_uniform_distribution(self):
        """When all items appear equally often, verify Gini reflects catalog coverage."""
        d = "/tmp/tb_gini_uni"
        ranked = {"users": [
            {"user_id": i, "ranked_items": list(range(1, 11))}
            for i in range(5)
        ]}
        gt = {"users": [{"user_id": i, "relevant_items": [1]} for i in range(5)]}
        cfg = {"topk": [10], "metrics": ["giniindex"], "num_items": 10}
        _write_case(d, ranked, gt, cfg)
        actual = _run_eval(d, "/tmp/tb_gini_uni_out.json")
        expected = _compute_expected(ranked, gt, cfg)
        _assert_match(actual, expected)

    def test_gini_large_catalog_sparse_recs(self):
        """Gini with large catalog where most items are never recommended."""
        d = "/tmp/tb_gini_sparse"
        ranked = {"users": [
            {"user_id": 0, "ranked_items": [1, 1, 1, 1, 1]},
        ]}
        gt = {"users": [{"user_id": 0, "relevant_items": [1]}]}
        cfg = {"topk": [5], "metrics": ["giniindex"], "num_items": 100}
        _write_case(d, ranked, gt, cfg)
        actual = _run_eval(d, "/tmp/tb_gini_sparse_out.json")
        expected = _compute_expected(ranked, gt, cfg)
        _assert_match(actual, expected)
        assert actual["giniindex@5"] > 0.9, (
            f"Gini should be very high with 1/100 coverage, got {actual['giniindex@5']}"
        )

    def test_shannon_entropy_normalization(self):
        """Entropy divided by count of unique items."""
        d = "/tmp/tb_ent_norm"
        ranked = {"users": [
            {"user_id": 0, "ranked_items": [1, 2, 3, 4, 5]},
            {"user_id": 1, "ranked_items": [1, 6, 7, 8, 9]},
            {"user_id": 2, "ranked_items": [1, 10, 11, 12, 13]},
        ]}
        gt = {"users": [{"user_id": i, "relevant_items": [1]} for i in range(3)]}
        cfg = {"topk": [5], "metrics": ["shannonentropy"], "num_items": 15}
        _write_case(d, ranked, gt, cfg)
        actual = _run_eval(d, "/tmp/tb_ent_norm_out.json")
        expected = _compute_expected(ranked, gt, cfg)
        _assert_match(actual, expected)

    def test_coverage_exact(self):
        d = "/tmp/tb_cov"
        ranked = {"users": [
            {"user_id": 0, "ranked_items": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]},
            {"user_id": 1, "ranked_items": [11, 12, 13, 14, 15, 16, 17, 18, 19, 20]},
        ]}
        gt = {"users": [
            {"user_id": 0, "relevant_items": [1]},
            {"user_id": 1, "relevant_items": [11]},
        ]}
        cfg = {"topk": [5, 10], "metrics": ["itemcoverage"], "num_items": 50}
        _write_case(d, ranked, gt, cfg)
        actual = _run_eval(d, "/tmp/tb_cov_out.json")
        assert abs(actual["itemcoverage@5"] - 10.0 / 50) < 1e-3
        assert abs(actual["itemcoverage@10"] - 20.0 / 50) < 1e-3


# ---------------------------------------------------------------------------
# Empty-user exclusion
# ---------------------------------------------------------------------------


class TestEmptyUserExclusion:
    def test_exclude_empty_users(self):
        d = "/tmp/tb_empty"
        ranked = {"users": [
            {"user_id": 0, "ranked_items": [1, 2, 3, 4, 5]},
            {"user_id": 1, "ranked_items": [1, 2, 3, 4, 5]},
            {"user_id": 2, "ranked_items": [1, 2, 3, 4, 5]},
            {"user_id": 3, "ranked_items": [1, 2, 3, 4, 5]},
        ]}
        gt = {"users": [
            {"user_id": 0, "relevant_items": [1]},
            {"user_id": 1, "relevant_items": []},
            {"user_id": 2, "relevant_items": [5]},
            {"user_id": 3, "relevant_items": []},
        ]}
        cfg = {"topk": [5], "metrics": ["recall", "hit", "mrr", "ndcg", "map", "precision"],
               "num_items": 10}
        _write_case(d, ranked, gt, cfg)
        actual = _run_eval(d, "/tmp/tb_empty_out.json")
        expected = _compute_expected(ranked, gt, cfg)
        _assert_match(actual, expected)
        assert abs(actual["recall@5"] - 1.0) < 1e-3
        assert abs(actual["hit@5"] - 1.0) < 1e-3

    def test_all_empty_does_not_crash(self):
        """If every user has no relevant items, tool should not crash."""
        d = "/tmp/tb_all_empty"
        ranked = {"users": [
            {"user_id": 0, "ranked_items": [1, 2, 3]},
            {"user_id": 1, "ranked_items": [4, 5, 6]},
        ]}
        gt = {"users": [
            {"user_id": 0, "relevant_items": []},
            {"user_id": 1, "relevant_items": []},
        ]}
        cfg = {"topk": [3], "metrics": ["recall", "ndcg", "itemcoverage"], "num_items": 10}
        _write_case(d, ranked, gt, cfg)
        r = subprocess.run(
            ["python3", "/app/eval_tool.py", d, "/tmp/tb_all_empty_out.json"],
            capture_output=True, text=True, timeout=60,
        )
        assert r.returncode == 0, f"Crashed on all-empty users: {r.stderr}"
        with open("/tmp/tb_all_empty_out.json") as f:
            actual = json.load(f)
        assert abs(actual.get("itemcoverage@3", -1) - 0.6) < 1e-3

    def test_empty_users_still_contribute_to_diversity(self):
        """Users with no relevant items should still contribute to diversity metrics."""
        d = "/tmp/tb_empty_div"
        ranked = {"users": [
            {"user_id": 0, "ranked_items": [1, 2, 3, 4, 5]},
            {"user_id": 1, "ranked_items": [6, 7, 8, 9, 10]},
        ]}
        gt = {"users": [
            {"user_id": 0, "relevant_items": [1]},
            {"user_id": 1, "relevant_items": []},
        ]}
        cfg = {"topk": [5], "metrics": ["recall", "itemcoverage", "shannonentropy"], "num_items": 10}
        _write_case(d, ranked, gt, cfg)
        actual = _run_eval(d, "/tmp/tb_empty_div_out.json")
        assert abs(actual["recall@5"] - 1.0) < 1e-3
        assert abs(actual["itemcoverage@5"] - 1.0) < 1e-3


# ---------------------------------------------------------------------------
# Large-scale randomized test
# ---------------------------------------------------------------------------


class TestLargeRandom:
    def test_large_dataset_correctness(self):
        """Verify all metrics on a 200-user, 500-item random dataset."""
        rng = np.random.RandomState(12345)
        d = "/tmp/tb_large"
        n_users = 200
        n_items = 500
        k_max = 50

        users_r = []
        users_g = []
        for uid in range(n_users):
            perm = rng.permutation(n_items) + 1
            ritems = perm[:k_max].tolist()
            n_rel = rng.randint(0, 20)
            rel = (rng.choice(n_items, max(n_rel, 0), replace=False) + 1).tolist()
            users_r.append({"user_id": uid, "ranked_items": ritems})
            users_g.append({"user_id": uid, "relevant_items": rel})

        ranked = {"users": users_r}
        gt = {"users": users_g}
        cfg = {
            "topk": [5, 10, 20, 50],
            "metrics": ["recall", "precision", "hit", "mrr", "ndcg", "map",
                        "itemcoverage", "giniindex", "shannonentropy"],
            "num_items": n_items,
        }
        _write_case(d, ranked, gt, cfg)
        actual = _run_eval(d, "/tmp/tb_large_out.json")
        expected = _compute_expected(ranked, gt, cfg)
        _assert_match(actual, expected)

    def test_medium_dataset_with_many_empty(self):
        """Dataset where 40% of users have no relevant items."""
        rng = np.random.RandomState(54321)
        d = "/tmp/tb_medium"
        n_users = 100
        n_items = 200
        k_max = 20

        users_r = []
        users_g = []
        for uid in range(n_users):
            perm = rng.permutation(n_items) + 1
            ritems = perm[:k_max].tolist()
            if uid % 5 < 2:
                rel = []
            else:
                n_rel = rng.randint(1, 15)
                rel = (rng.choice(n_items, n_rel, replace=False) + 1).tolist()
            users_r.append({"user_id": uid, "ranked_items": ritems})
            users_g.append({"user_id": uid, "relevant_items": rel})

        ranked = {"users": users_r}
        gt = {"users": users_g}
        cfg = {
            "topk": [5, 10, 20],
            "metrics": ["recall", "precision", "hit", "mrr", "ndcg", "map",
                        "itemcoverage", "giniindex", "shannonentropy"],
            "num_items": n_items,
        }
        _write_case(d, ranked, gt, cfg)
        actual = _run_eval(d, "/tmp/tb_medium_out.json")
        expected = _compute_expected(ranked, gt, cfg)
        _assert_match(actual, expected)


# ---------------------------------------------------------------------------
# Score conversion pipeline with randomized data
# ---------------------------------------------------------------------------


class TestPipelineLargeRandom:
    def test_pipeline_random_scores(self):
        """Full pipeline on a random score matrix with all metrics."""
        rng = np.random.RandomState(99999)
        d = "/tmp/tb_pipeline_rand"
        os.makedirs(d, exist_ok=True)
        n_users = 30
        n_items = 50

        scores = rng.rand(n_users, n_items).tolist()
        relevance = (rng.rand(n_users, n_items) > 0.85).astype(int).tolist()
        # Make some users have no relevant items
        for i in [5, 10, 15, 20, 25]:
            relevance[i] = [0] * n_items

        config = {
            "topk": [5, 10, 20],
            "metrics": ["recall", "precision", "hit", "mrr", "ndcg", "map",
                        "itemcoverage", "giniindex", "shannonentropy"],
            "num_items": n_items
        }

        with open(os.path.join(d, "scores.json"), "w") as f:
            json.dump(scores, f)
        with open(os.path.join(d, "relevance.json"), "w") as f:
            json.dump(relevance, f)
        with open(os.path.join(d, "eval_config.yaml"), "w") as f:
            yaml.dump(config, f)

        ranked, gt, eval_cfg = _ref_convert_scores(scores, relevance, config)
        expected = _compute_expected(ranked, gt, eval_cfg)

        actual = _run_pipeline(d, "/tmp/tb_pipeline_rand_proc", "/tmp/tb_pipeline_rand_out.json")
        _assert_match(actual, expected)

    def test_pipeline_large_catalog(self):
        """Pipeline where num_items in config exceeds score matrix width."""
        rng = np.random.RandomState(77777)
        d = "/tmp/tb_pipeline_lgcat"
        os.makedirs(d, exist_ok=True)
        n_users = 15
        n_scored = 20
        n_catalog = 50  # larger than scored items

        scores = rng.rand(n_users, n_scored).tolist()
        relevance = (rng.rand(n_users, n_scored) > 0.8).astype(int).tolist()

        config = {
            "topk": [5, 10],
            "metrics": ["recall", "ndcg", "itemcoverage", "giniindex", "shannonentropy"],
            "num_items": n_catalog  # larger than n_scored
        }

        with open(os.path.join(d, "scores.json"), "w") as f:
            json.dump(scores, f)
        with open(os.path.join(d, "relevance.json"), "w") as f:
            json.dump(relevance, f)
        with open(os.path.join(d, "eval_config.yaml"), "w") as f:
            yaml.dump(config, f)

        ranked, gt, eval_cfg = _ref_convert_scores(scores, relevance, config)
        expected = _compute_expected(ranked, gt, eval_cfg)

        actual = _run_pipeline(d, "/tmp/tb_pipeline_lgcat_proc", "/tmp/tb_pipeline_lgcat_out.json")
        _assert_match(actual, expected)
        # Diversity metrics should use num_items=50, not 20
        assert actual["itemcoverage@5"] < 1.0, (
            "ItemCoverage should be < 1.0 when catalog (50) is larger than scored items (20)"
        )


# ---------------------------------------------------------------------------
# Output format
# ---------------------------------------------------------------------------


class TestOutputFormat:
    def test_keys_are_lowercase(self):
        actual = _run_eval("/app/data/scenario1", "/tmp/tb_fmt_out.json")
        for key in actual:
            assert key == key.lower(), f"Key not lowercase: {key}"
            assert "@" in key, f"Key missing @: {key}"

    def test_values_are_rounded(self):
        actual = _run_eval("/app/data/scenario3", "/tmp/tb_fmt_round.json")
        for key, val in actual.items():
            s = str(val)
            if "." in s:
                decimals = len(s.split(".")[1])
                assert decimals <= 4, f"{key}={val} has {decimals} decimal places (max 4)"

    def test_creates_parent_dirs(self):
        out = "/tmp/tb_nested/sub/dir/result.json"
        if os.path.exists(out):
            os.remove(out)
        actual = _run_eval("/app/data/scenario1", out)
        assert os.path.isfile(out)

    def test_case_insensitive_metrics(self):
        """Config may use mixed case metric names."""
        d = "/tmp/tb_casein"
        ranked = {"users": [{"user_id": 0, "ranked_items": [1, 2, 3]}]}
        gt = {"users": [{"user_id": 0, "relevant_items": [1]}]}
        cfg = {"topk": [3], "metrics": ["RECALL", "Precision", "HIT"], "num_items": 5}
        _write_case(d, ranked, gt, cfg)
        actual = _run_eval(d, "/tmp/tb_casein_out.json")
        assert "recall@3" in actual
        assert "precision@3" in actual
        assert "hit@3" in actual
