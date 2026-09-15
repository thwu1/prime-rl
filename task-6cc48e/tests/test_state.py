"""Tests for search evaluation pipeline forensic audit report."""

import pytest
import json
import math
import os
from collections import defaultdict

MAX_GRADE = 3
K_CUTOFF = 10
TOLERANCE = 0.005
RRF_TOLERANCE = 0.003
CLICK_MODEL_TOL = 0.05
TAU_TOL = 0.01
ORACLE_NDCG_TOL = 0.005
ORACLE_PCT_TOL = 1.0

SYSTEMS = ["bm25", "tfidf", "embedding", "sparse", "hybrid"]
CATEGORIES = ["navigational", "informational", "transactional"]

BUGGY_FUNCTIONS = {"load_qrels", "compute_ndcg", "compute_err", "compute_map"}


# ---------------------------------------------------------------------------
# Reference implementations for core metrics
# ---------------------------------------------------------------------------

def load_qrels_correct(path):
    """Load qrels taking MAX grade for duplicate query-doc pairs."""
    qrels = {}
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 4:
                continue
            qid = parts[0]
            docid = parts[2]
            grade = int(parts[3])
            qrels.setdefault(qid, {})
            qrels[qid][docid] = max(qrels[qid].get(docid, -1), grade)
    return qrels


def find_duplicate_qrels(path):
    """Find query-doc pairs with multiple entries having different grades."""
    seen = {}
    duplicates = set()
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 4:
                continue
            qid = parts[0]
            docid = parts[2]
            grade = int(parts[3])
            key = (qid, docid)
            if key in seen and seen[key] != grade:
                duplicates.add(key)
            seen[key] = grade
    return duplicates


def count_invalid_clicks(path):
    """Count click log entries with position <= 0."""
    count = 0
    with open(path) as f:
        f.readline()
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) < 4:
                continue
            pos = int(parts[2])
            if pos <= 0:
                count += 1
    return count


def load_run(path):
    run = {}
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 6:
                continue
            qid = parts[0]
            docid = parts[2]
            rank = int(parts[3])
            score = float(parts[4])
            run.setdefault(qid, []).append((docid, rank, score))
    for qid in run:
        run[qid].sort(key=lambda x: x[1])
    return run


def ref_ndcg(qrels_q, ranked, k=K_CUTOFF):
    dcg = 0.0
    for i in range(min(k, len(ranked))):
        g = qrels_q.get(ranked[i][0], 0)
        dcg += (2 ** g - 1) / math.log2(i + 2)
    grades = sorted(qrels_q.values(), reverse=True)
    idcg = 0.0
    for i in range(min(k, len(grades))):
        idcg += (2 ** grades[i] - 1) / math.log2(i + 2)
    return dcg / idcg if idcg > 0 else 0.0


def ref_err(qrels_q, ranked, k=K_CUTOFF):
    val = 0.0
    p = 1.0
    for r in range(min(k, len(ranked))):
        g = qrels_q.get(ranked[r][0], 0)
        R = (2 ** g - 1) / (2 ** MAX_GRADE)
        val += (1.0 / (r + 1)) * p * R
        p *= (1 - R)
    return val


def ref_map(qrels_q, ranked, k=K_CUTOFF, threshold=1):
    R = sum(1 for g in qrels_q.values() if g >= threshold)
    if R == 0:
        return 0.0
    n_rel = 0
    s = 0.0
    for j in range(min(k, len(ranked))):
        g = qrels_q.get(ranked[j][0], 0)
        if g >= threshold:
            n_rel += 1
            s += n_rel / (j + 1)
    return s / R


def mean_metric(qrels, run, fn):
    vals = []
    for qid in sorted(qrels):
        r = run.get(qid, [])
        vals.append(fn(qrels[qid], r))
    return sum(vals) / len(vals) if vals else 0.0


def mean_metric_category(qrels, run, fn, query_cats, category):
    vals = []
    for qid in sorted(qrels):
        if query_cats.get(qid) != category:
            continue
        r = run.get(qid, [])
        vals.append(fn(qrels[qid], r))
    return sum(vals) / len(vals) if vals else 0.0


def per_query_metric(qrels, run, fn):
    """Return dict of {qid: metric_value}."""
    result = {}
    for qid in sorted(qrels):
        r = run.get(qid, [])
        result[qid] = fn(qrels[qid], r)
    return result


def rrf_fuse(runs_dict, k_param):
    fused = {}
    for sys_name in sorted(runs_dict):
        run = runs_dict[sys_name]
        for qid in run:
            fused.setdefault(qid, {})
            for docid, rank, _ in run[qid]:
                fused[qid][docid] = fused[qid].get(docid, 0.0) + 1.0 / (k_param + rank)
    result = {}
    for qid in fused:
        docs = sorted(fused[qid].items(), key=lambda x: (-x[1], x[0]))
        result[qid] = [(d, i + 1, s) for i, (d, s) in enumerate(docs)]
    return result


# ---------------------------------------------------------------------------
# Reference implementations for expert-level analysis components
# ---------------------------------------------------------------------------

def compute_position_ctr(click_path):
    """Compute per-position CTR from click log, excluding invalid entries."""
    pos_clicks = defaultdict(int)
    pos_imps = defaultdict(int)
    with open(click_path) as f:
        f.readline()  # skip header
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) < 4:
                continue
            pos = int(parts[2])
            clicked = int(parts[3])
            if pos <= 0:
                continue
            pos_imps[pos] += 1
            pos_clicks[pos] += clicked
    ctr = {}
    for p in sorted(pos_imps):
        ctr[p] = pos_clicks[p] / pos_imps[p] if pos_imps[p] > 0 else 0.0
    return ctr


def fit_power_law(ctr_dict):
    """Fit CTR(p) = a * p^(-b) via log-log OLS. Returns (b, r_squared).
    Excludes positions with CTR == 0 (log undefined)."""
    xs = []
    ys = []
    for p, c in sorted(ctr_dict.items()):
        if c > 0:
            xs.append(math.log(p))
            ys.append(math.log(c))
    if len(xs) < 2:
        return 0.0, 0.0
    n = len(xs)
    sx = sum(xs)
    sy = sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    denom = n * sxx - sx * sx
    if abs(denom) < 1e-15:
        return 0.0, 0.0
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    y_mean = sy / n
    ss_tot = sum((y - y_mean) ** 2 for y in ys)
    ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
    r_sq = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    exponent = -slope  # CTR = a * p^(-b), so log(CTR) = log(a) - b*log(p)
    return exponent, r_sq


def kendall_tau_a(values1, values2, keys):
    """Kendall tau-a between two orderings defined by value dicts."""
    n = len(keys)
    concordant = 0
    discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            a, b = keys[i], keys[j]
            d1 = values1[a] - values1[b]
            d2 = values2[a] - values2[b]
            prod = d1 * d2
            if prod > 0:
                concordant += 1
            elif prod < 0:
                discordant += 1
    total = concordant + discordant
    return (concordant - discordant) / total if total > 0 else 0.0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ref_data():
    qrels = load_qrels_correct("/app/data/qrels.txt")
    runs = {}
    for sn in SYSTEMS:
        runs[sn] = load_run(f"/app/data/{sn}.run")
    with open("/app/data/query_taxonomy.json") as f:
        cats = json.load(f)
    return qrels, runs, cats


@pytest.fixture(scope="module")
def agent_report():
    path = "/app/audit_report.json"
    assert os.path.exists(path), "audit_report.json not found at /app/audit_report.json"
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Tests: report structure
# ---------------------------------------------------------------------------

def test_report_structure(agent_report):
    """Verify the audit report has all required top-level keys and structure."""
    for key in ["pipeline_bugs", "data_issues", "corrected_metrics",
                "category_best_system", "fusion", "click_model",
                "metric_concordance", "oracle_analysis"]:
        assert key in agent_report, f"Missing top-level key: {key}"

    assert isinstance(agent_report["pipeline_bugs"], list)
    assert "duplicate_qrels" in agent_report["data_issues"]
    assert "invalid_click_count" in agent_report["data_issues"]

    for sn in SYSTEMS:
        assert sn in agent_report["corrected_metrics"], f"Missing system: {sn}"
        for m in ["ndcg@10", "err@10", "map@10"]:
            assert m in agent_report["corrected_metrics"][sn], \
                f"Missing metric {m} for {sn}"

    for cat in CATEGORIES:
        assert cat in agent_report["category_best_system"], \
            f"Missing category: {cat}"

    assert "optimal_k" in agent_report["fusion"]
    assert "fused_ndcg@10" in agent_report["fusion"]

    assert "power_law_exponent" in agent_report["click_model"]
    assert "r_squared" in agent_report["click_model"]

    for key in ["ndcg_err_tau", "ndcg_map_tau", "err_map_tau"]:
        assert key in agent_report["metric_concordance"], \
            f"Missing concordance key: {key}"

    for key in ["best_single_system", "best_single_ndcg",
                "oracle_ndcg", "oracle_improvement_pct"]:
        assert key in agent_report["oracle_analysis"], \
            f"Missing oracle key: {key}"


# ---------------------------------------------------------------------------
# Tests: pipeline bugs
# ---------------------------------------------------------------------------

def test_pipeline_bugs_identified(agent_report):
    """Verify all four buggy functions are identified in the report."""
    reported_funcs = set()
    for bug in agent_report["pipeline_bugs"]:
        assert "function_name" in bug, "Bug entry missing function_name"
        assert "description" in bug, "Bug entry missing description"
        reported_funcs.add(bug["function_name"])

    for func in BUGGY_FUNCTIONS:
        assert func in reported_funcs, \
            f"Bug in '{func}' was not identified. Reported: {sorted(reported_funcs)}"


# ---------------------------------------------------------------------------
# Tests: data quality
# ---------------------------------------------------------------------------

def test_duplicate_qrels_found(agent_report):
    """Verify all duplicate qrels pairs with conflicting grades are found."""
    expected = find_duplicate_qrels("/app/data/qrels.txt")
    expected_set = {(q, d) for q, d in expected}
    reported = agent_report["data_issues"]["duplicate_qrels"]
    reported_set = {(pair[0], pair[1]) for pair in reported}
    assert reported_set == expected_set, \
        f"Duplicate qrels mismatch.\nExpected: {sorted(expected_set)}\nGot: {sorted(reported_set)}"


def test_invalid_clicks_count(agent_report):
    """Verify count of click entries with non-positive position."""
    expected = count_invalid_clicks("/app/data/clicks.tsv")
    actual = agent_report["data_issues"]["invalid_click_count"]
    assert actual == expected, \
        f"Invalid click count: expected {expected}, got {actual}"


# ---------------------------------------------------------------------------
# Tests: corrected metrics
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sys_name", SYSTEMS)
def test_corrected_ndcg(ref_data, agent_report, sys_name):
    qrels, runs, _ = ref_data
    expected = mean_metric(qrels, runs[sys_name], ref_ndcg)
    actual = agent_report["corrected_metrics"][sys_name]["ndcg@10"]
    assert abs(expected - actual) < TOLERANCE, \
        f"{sys_name} nDCG@10: expected {expected:.6f}, got {actual}"


@pytest.mark.parametrize("sys_name", SYSTEMS)
def test_corrected_err(ref_data, agent_report, sys_name):
    qrels, runs, _ = ref_data
    expected = mean_metric(qrels, runs[sys_name], ref_err)
    actual = agent_report["corrected_metrics"][sys_name]["err@10"]
    assert abs(expected - actual) < TOLERANCE, \
        f"{sys_name} ERR@10: expected {expected:.6f}, got {actual}"


@pytest.mark.parametrize("sys_name", SYSTEMS)
def test_corrected_map(ref_data, agent_report, sys_name):
    qrels, runs, _ = ref_data
    expected = mean_metric(qrels, runs[sys_name], ref_map)
    actual = agent_report["corrected_metrics"][sys_name]["map@10"]
    assert abs(expected - actual) < TOLERANCE, \
        f"{sys_name} MAP@10: expected {expected:.6f}, got {actual}"


# ---------------------------------------------------------------------------
# Tests: category best system
# ---------------------------------------------------------------------------

def test_category_best_system(ref_data, agent_report):
    qrels, runs, cats = ref_data
    for category in CATEGORIES:
        best_sys = None
        best_ndcg = -1.0
        for sys_name in SYSTEMS:
            ndcg = mean_metric_category(
                qrels, runs[sys_name], ref_ndcg, cats, category
            )
            if ndcg > best_ndcg:
                best_ndcg = ndcg
                best_sys = sys_name
        reported = agent_report["category_best_system"][category]
        assert reported == best_sys, \
            f"Category '{category}': expected '{best_sys}', got '{reported}'"


# ---------------------------------------------------------------------------
# Tests: RRF fusion
# ---------------------------------------------------------------------------

def test_fusion_optimal_k(ref_data, agent_report):
    qrels, runs, _ = ref_data
    best_k, best_ndcg = 1, -1.0
    for k in range(1, 101):
        fused = rrf_fuse(runs, k)
        n = mean_metric(qrels, fused, ref_ndcg)
        if n > best_ndcg:
            best_ndcg = n
            best_k = k
    agent_k = agent_report["fusion"]["optimal_k"]
    assert isinstance(agent_k, int), f"optimal_k must be int, got {type(agent_k)}"
    assert 1 <= agent_k <= 100, f"optimal_k must be in [1,100], got {agent_k}"
    fused_agent = rrf_fuse(runs, agent_k)
    agent_k_ndcg = mean_metric(qrels, fused_agent, ref_ndcg)
    assert agent_k_ndcg >= best_ndcg - RRF_TOLERANCE, \
        f"Agent k={agent_k} gives nDCG={agent_k_ndcg:.6f}, " \
        f"but best k={best_k} gives {best_ndcg:.6f}"


def test_fusion_reported_ndcg(ref_data, agent_report):
    qrels, runs, _ = ref_data
    agent_k = agent_report["fusion"]["optimal_k"]
    if not isinstance(agent_k, int) or not (1 <= agent_k <= 100):
        pytest.skip("optimal_k invalid, tested elsewhere")
    fused = rrf_fuse(runs, agent_k)
    expected = mean_metric(qrels, fused, ref_ndcg)
    reported = agent_report["fusion"]["fused_ndcg@10"]
    assert abs(expected - reported) < TOLERANCE, \
        f"Reported fusion nDCG={reported} for k={agent_k}, computed {expected:.6f}"


# ---------------------------------------------------------------------------
# Tests: click model (position-bias power-law fit)
# ---------------------------------------------------------------------------

def test_click_model_exponent(agent_report):
    """Verify power-law exponent from position-bias click model."""
    ctr = compute_position_ctr("/app/data/clicks.tsv")
    expected_b, expected_r2 = fit_power_law(ctr)
    reported_b = agent_report["click_model"]["power_law_exponent"]
    assert abs(expected_b - reported_b) < CLICK_MODEL_TOL, \
        f"Power law exponent: expected {expected_b:.4f}, got {reported_b}"


def test_click_model_r_squared(agent_report):
    """Verify R² of the power-law fit."""
    ctr = compute_position_ctr("/app/data/clicks.tsv")
    expected_b, expected_r2 = fit_power_law(ctr)
    reported_r2 = agent_report["click_model"]["r_squared"]
    assert abs(expected_r2 - reported_r2) < CLICK_MODEL_TOL, \
        f"R²: expected {expected_r2:.4f}, got {reported_r2}"


# ---------------------------------------------------------------------------
# Tests: inter-metric concordance (Kendall's tau)
# ---------------------------------------------------------------------------

def test_metric_concordance(ref_data, agent_report):
    """Verify Kendall tau-a between metric-induced system rankings."""
    qrels, runs, _ = ref_data
    ndcg_vals = {s: mean_metric(qrels, runs[s], ref_ndcg) for s in SYSTEMS}
    err_vals = {s: mean_metric(qrels, runs[s], ref_err) for s in SYSTEMS}
    map_vals = {s: mean_metric(qrels, runs[s], ref_map) for s in SYSTEMS}

    keys = sorted(SYSTEMS)

    exp_ne = kendall_tau_a(ndcg_vals, err_vals, keys)
    exp_nm = kendall_tau_a(ndcg_vals, map_vals, keys)
    exp_em = kendall_tau_a(err_vals, map_vals, keys)

    rep = agent_report["metric_concordance"]
    assert abs(exp_ne - rep["ndcg_err_tau"]) < TAU_TOL, \
        f"nDCG-ERR tau: expected {exp_ne:.4f}, got {rep['ndcg_err_tau']}"
    assert abs(exp_nm - rep["ndcg_map_tau"]) < TAU_TOL, \
        f"nDCG-MAP tau: expected {exp_nm:.4f}, got {rep['ndcg_map_tau']}"
    assert abs(exp_em - rep["err_map_tau"]) < TAU_TOL, \
        f"ERR-MAP tau: expected {exp_em:.4f}, got {rep['err_map_tau']}"


# ---------------------------------------------------------------------------
# Tests: oracle per-query system selection
# ---------------------------------------------------------------------------

def test_oracle_best_single_system(ref_data, agent_report):
    """Verify identification of the best single system by mean nDCG@10."""
    qrels, runs, _ = ref_data
    best_sys = None
    best_ndcg = -1.0
    for sn in SYSTEMS:
        n = mean_metric(qrels, runs[sn], ref_ndcg)
        if n > best_ndcg:
            best_ndcg = n
            best_sys = sn
    reported = agent_report["oracle_analysis"]["best_single_system"]
    assert reported == best_sys, \
        f"Best single system: expected '{best_sys}', got '{reported}'"
    reported_ndcg = agent_report["oracle_analysis"]["best_single_ndcg"]
    assert abs(best_ndcg - reported_ndcg) < ORACLE_NDCG_TOL, \
        f"Best single nDCG: expected {best_ndcg:.6f}, got {reported_ndcg}"


def test_oracle_ndcg(ref_data, agent_report):
    """Verify oracle nDCG@10 (per-query best system selection)."""
    qrels, runs, _ = ref_data
    pq = {}
    for sn in SYSTEMS:
        pq[sn] = per_query_metric(qrels, runs[sn], ref_ndcg)
    oracle_vals = []
    for qid in sorted(qrels):
        best = max(pq[sn][qid] for sn in SYSTEMS)
        oracle_vals.append(best)
    expected_oracle = sum(oracle_vals) / len(oracle_vals) if oracle_vals else 0.0
    reported = agent_report["oracle_analysis"]["oracle_ndcg"]
    assert abs(expected_oracle - reported) < ORACLE_NDCG_TOL, \
        f"Oracle nDCG: expected {expected_oracle:.6f}, got {reported}"


def test_oracle_improvement(ref_data, agent_report):
    """Verify percentage improvement of oracle over best single system."""
    qrels, runs, _ = ref_data
    best_ndcg = max(mean_metric(qrels, runs[sn], ref_ndcg) for sn in SYSTEMS)
    pq = {}
    for sn in SYSTEMS:
        pq[sn] = per_query_metric(qrels, runs[sn], ref_ndcg)
    oracle_vals = []
    for qid in sorted(qrels):
        oracle_vals.append(max(pq[sn][qid] for sn in SYSTEMS))
    oracle_ndcg = sum(oracle_vals) / len(oracle_vals) if oracle_vals else 0.0
    expected_pct = (oracle_ndcg - best_ndcg) / best_ndcg * 100.0 if best_ndcg > 0 else 0.0
    reported = agent_report["oracle_analysis"]["oracle_improvement_pct"]
    assert abs(expected_pct - reported) < ORACLE_PCT_TOL, \
        f"Oracle improvement: expected {expected_pct:.2f}%, got {reported}"
