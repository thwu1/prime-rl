
import json
import math
import os
import pytest
import numpy as np
from scipy.optimize import minimize_scalar
from scipy.stats import spearmanr


RESULTS_DIR = "/app/results"
DATA_PATH = "/tests/reference_data.json"
TOL_EXACT = 1e-6
TOL_NUMERIC = 1e-3


def load_data():
    with open(DATA_PATH) as f:
        return json.load(f)


def load_result(filename):
    path = os.path.join(RESULTS_DIR, filename)
    assert os.path.exists(path), f"Missing output file: {path}"
    with open(path) as f:
        return json.load(f)


# ---- Reference implementations ----

def ref_brier_scores(data):
    scores = {}
    for problem in data["problems"]:
        outcome = 1.0 if problem["resolution"] == "Yes" else 0.0
        for fid, p_yes in problem["forecasts"].items():
            brier = (p_yes - outcome) ** 2
            scores.setdefault(fid, []).append(brier)
    return {fid: 1.0 - float(np.mean(vals)) for fid, vals in scores.items()}


def ref_log_scores(data):
    scores = {}
    for problem in data["problems"]:
        res = problem["resolution"]
        for fid, p_yes in problem["forecasts"].items():
            p_correct = p_yes if res == "Yes" else 1.0 - p_yes
            scores.setdefault(fid, []).append(math.log(max(p_correct, 1e-15)))
    return {fid: float(np.mean(vals)) for fid, vals in scores.items()}


def ref_crra_gamma0(data):
    """Risk-neutral (all-in) returns."""
    returns = {}
    for problem in data["problems"]:
        q = problem["market_price_yes"]
        res = problem["resolution"]
        for fid, p in problem["forecasts"].items():
            if p > q:
                ret = (1.0 / q - 1.0) if res == "Yes" else -1.0
            elif p < q:
                ret = (1.0 / (1.0 - q) - 1.0) if res == "No" else -1.0
            else:
                ret = 0.0
            returns.setdefault(fid, []).append(ret)
    return {fid: float(np.mean(vals)) for fid, vals in returns.items()}


def ref_crra_gamma1(data):
    """Kelly criterion (log utility) returns."""
    returns = {}
    for problem in data["problems"]:
        q = problem["market_price_yes"]
        res = problem["resolution"]
        for fid, p in problem["forecasts"].items():
            if p > q:
                alpha = (p - q) / (1.0 - q)
                if res == "Yes":
                    ret = alpha * (1.0 - q) / q
                else:
                    ret = -alpha
            elif p < q:
                alpha = (q - p) / q
                if res == "No":
                    ret = alpha * q / (1.0 - q)
                else:
                    ret = -alpha
            else:
                ret = 0.0
            returns.setdefault(fid, []).append(ret)
    return {fid: float(np.mean(vals)) for fid, vals in returns.items()}


def _crra_optimal_return_05(p, q, resolution):
    """Compute return under CRRA gamma=0.5 for a single binary problem."""
    gamma = 0.5

    def neg_eu_yes(alpha):
        w_win = 1.0 + alpha * (1.0 - q) / q
        w_lose = 1.0 - alpha
        if w_win <= 0 or w_lose <= 0:
            return 1e10
        return -(p * w_win ** (1 - gamma) / (1 - gamma) +
                 (1 - p) * w_lose ** (1 - gamma) / (1 - gamma))

    def neg_eu_no(alpha):
        w_win = 1.0 + alpha * q / (1.0 - q)
        w_lose = 1.0 - alpha
        if w_win <= 0 or w_lose <= 0:
            return 1e10
        return -((1 - p) * w_win ** (1 - gamma) / (1 - gamma) +
                 p * w_lose ** (1 - gamma) / (1 - gamma))

    eu_notrade = 1.0 ** (1 - gamma) / (1 - gamma)

    res_yes = minimize_scalar(neg_eu_yes, bounds=(0, 1), method="bounded")
    eu_yes = -res_yes.fun
    alpha_yes = res_yes.x

    res_no = minimize_scalar(neg_eu_no, bounds=(0, 1), method="bounded")
    eu_no = -res_no.fun
    alpha_no = res_no.x

    if eu_yes >= eu_no and eu_yes > eu_notrade + 1e-12:
        alpha = alpha_yes
        if resolution == "Yes":
            return alpha * (1.0 - q) / q
        else:
            return -alpha
    elif eu_no > eu_yes and eu_no > eu_notrade + 1e-12:
        alpha = alpha_no
        if resolution == "No":
            return alpha * q / (1.0 - q)
        else:
            return -alpha
    else:
        return 0.0


def ref_crra_gamma05(data):
    returns = {}
    for problem in data["problems"]:
        q = problem["market_price_yes"]
        res = problem["resolution"]
        for fid, p in problem["forecasts"].items():
            ret = _crra_optimal_return_05(p, q, res)
            returns.setdefault(fid, []).append(ret)
    return {fid: float(np.mean(vals)) for fid, vals in returns.items()}


def ref_bt_ranking(data):
    """Returns forecaster IDs sorted best-to-worst by Bradley-Terry skill."""
    forecaster_ids = sorted(data["problems"][0]["forecasts"].keys())
    n = len(forecaster_ids)
    fid_idx = {fid: i for i, fid in enumerate(forecaster_ids)}

    wins = np.zeros((n, n))
    comparisons = np.zeros((n, n))

    for problem in data["problems"]:
        res = problem["resolution"]
        forecasts = problem["forecasts"]
        log_scores = {}
        for fid, p_yes in forecasts.items():
            p_correct = p_yes if res == "Yes" else 1.0 - p_yes
            log_scores[fid] = math.log(max(p_correct, 1e-15))

        fids = list(log_scores.keys())
        for i_idx in range(len(fids)):
            for j_idx in range(i_idx + 1, len(fids)):
                fi, fj = fids[i_idx], fids[j_idx]
                si, sj = log_scores[fi], log_scores[fj]
                ii, jj = fid_idx[fi], fid_idx[fj]
                comparisons[ii][jj] += 1
                comparisons[jj][ii] += 1
                if si > sj:
                    wins[ii][jj] += 1
                elif sj > si:
                    wins[jj][ii] += 1
                else:
                    wins[ii][jj] += 0.5
                    wins[jj][ii] += 0.5

    total_wins = wins.sum(axis=1)
    theta = np.ones(n)

    for _ in range(2000):
        new_theta = np.ones(n)
        for i in range(n):
            denom = 0.0
            for j in range(n):
                if i != j and comparisons[i][j] > 0:
                    denom += comparisons[i][j] / (theta[i] + theta[j])
            if denom > 0 and total_wins[i] > 0:
                new_theta[i] = total_wins[i] / denom
            else:
                new_theta[i] = theta[i]
        if np.max(np.abs(new_theta - theta)) < 1e-10:
            theta = new_theta
            break
        theta = new_theta

    log_mean = np.mean(np.log(theta))
    theta = theta / np.exp(log_mean)

    ranked = sorted(range(n), key=lambda i: theta[i], reverse=True)
    return [forecaster_ids[i] for i in ranked]


def get_ranking(scores):
    return sorted(scores.keys(), key=lambda k: scores[k], reverse=True)


# ---- Tests ----

class TestOutputFilesExist:
    def test_brier_scores_exist(self):
        assert os.path.exists(os.path.join(RESULTS_DIR, "brier_scores.json"))

    def test_log_scores_exist(self):
        assert os.path.exists(os.path.join(RESULTS_DIR, "log_scores.json"))

    def test_crra_returns_exist(self):
        assert os.path.exists(os.path.join(RESULTS_DIR, "crra_returns.json"))

    def test_bt_skills_exist(self):
        assert os.path.exists(os.path.join(RESULTS_DIR, "bt_skills.json"))

    def test_correlation_matrix_exist(self):
        assert os.path.exists(os.path.join(RESULTS_DIR, "correlation_matrix.json"))

    def test_rankings_exist(self):
        assert os.path.exists(os.path.join(RESULTS_DIR, "rankings.json"))


class TestBrierScores:
    def test_brier_values(self):
        data = load_data()
        result = load_result("brier_scores.json")
        ref = ref_brier_scores(data)
        for fid in ref:
            assert fid in result, f"Missing forecaster {fid} in brier_scores"
            assert abs(result[fid] - ref[fid]) < TOL_EXACT, \
                f"Brier score mismatch for {fid}: got {result[fid]}, expected {ref[fid]}"

    def test_brier_range(self):
        result = load_result("brier_scores.json")
        for fid, val in result.items():
            assert 0.0 <= val <= 1.0, f"Brier (1-mean) out of range for {fid}: {val}"

    def test_brier_ranking_top(self):
        data = load_data()
        result = load_result("brier_scores.json")
        ref = ref_brier_scores(data)
        ref_top = get_ranking(ref)[0]
        res_top = get_ranking(result)[0]
        assert ref_top == res_top, f"Top Brier forecaster mismatch: expected {ref_top}, got {res_top}"


class TestLogScores:
    def test_log_score_values(self):
        data = load_data()
        result = load_result("log_scores.json")
        ref = ref_log_scores(data)
        for fid in ref:
            assert fid in result, f"Missing forecaster {fid} in log_scores"
            assert abs(result[fid] - ref[fid]) < TOL_EXACT, \
                f"Log score mismatch for {fid}: got {result[fid]}, expected {ref[fid]}"

    def test_log_score_negative(self):
        result = load_result("log_scores.json")
        for fid, val in result.items():
            assert val < 0, f"Log score should be negative for {fid}: {val}"


class TestCRRAReturns:
    def test_crra_gamma0(self):
        data = load_data()
        result = load_result("crra_returns.json")
        ref = ref_crra_gamma0(data)
        for fid in ref:
            assert fid in result, f"Missing forecaster {fid}"
            got = result[fid]["gamma_0"]
            assert abs(got - ref[fid]) < TOL_EXACT, \
                f"CRRA gamma=0 mismatch for {fid}: got {got}, expected {ref[fid]}"

    def test_crra_gamma1(self):
        data = load_data()
        result = load_result("crra_returns.json")
        ref = ref_crra_gamma1(data)
        for fid in ref:
            assert fid in result, f"Missing forecaster {fid}"
            got = result[fid]["gamma_1"]
            assert abs(got - ref[fid]) < TOL_EXACT, \
                f"CRRA gamma=1 mismatch for {fid}: got {got}, expected {ref[fid]}"

    def test_crra_gamma05(self):
        data = load_data()
        result = load_result("crra_returns.json")
        ref = ref_crra_gamma05(data)
        for fid in ref:
            assert fid in result, f"Missing forecaster {fid}"
            got = result[fid]["gamma_0.5"]
            assert abs(got - ref[fid]) < TOL_NUMERIC, \
                f"CRRA gamma=0.5 mismatch for {fid}: got {got}, expected {ref[fid]}"

    def test_crra_has_all_gamma_keys(self):
        result = load_result("crra_returns.json")
        for fid, vals in result.items():
            assert "gamma_0" in vals, f"Missing gamma_0 for {fid}"
            assert "gamma_0.5" in vals, f"Missing gamma_0.5 for {fid}"
            assert "gamma_1" in vals, f"Missing gamma_1 for {fid}"


class TestBradleyTerry:
    def test_bt_skills_positive(self):
        result = load_result("bt_skills.json")
        for fid, val in result.items():
            assert val > 0, f"BT skill should be positive for {fid}: {val}"

    def test_bt_geometric_mean_one(self):
        result = load_result("bt_skills.json")
        values = list(result.values())
        log_mean = np.mean([math.log(v) for v in values])
        geo_mean = math.exp(log_mean)
        assert abs(geo_mean - 1.0) < TOL_EXACT, \
            f"BT geometric mean should be 1.0, got {geo_mean}"

    def test_bt_ranking_order(self):
        data = load_data()
        result = load_result("bt_skills.json")
        ref_rank = ref_bt_ranking(data)
        res_rank = sorted(result.keys(), key=lambda k: result[k], reverse=True)
        assert ref_rank[0] == res_rank[0], \
            f"Top BT forecaster mismatch: expected {ref_rank[0]}, got {res_rank[0]}"
        assert ref_rank[-1] == res_rank[-1], \
            f"Bottom BT forecaster mismatch: expected {ref_rank[-1]}, got {res_rank[-1]}"


class TestCorrelationMatrix:
    def test_correlation_structure(self):
        result = load_result("correlation_matrix.json")
        assert "methods" in result, "Missing 'methods' key"
        assert "matrix" in result, "Missing 'matrix' key"
        methods = result["methods"]
        matrix = result["matrix"]
        n = len(methods)
        assert n == 5, f"Expected 5 methods, got {n}"
        assert len(matrix) == n, f"Matrix row count mismatch"
        for row in matrix:
            assert len(row) == n, f"Matrix column count mismatch"

    def test_correlation_diagonal(self):
        result = load_result("correlation_matrix.json")
        matrix = result["matrix"]
        for i in range(len(matrix)):
            assert abs(matrix[i][i] - 1.0) < TOL_EXACT, \
                f"Diagonal element [{i}][{i}] should be 1.0, got {matrix[i][i]}"

    def test_correlation_symmetry(self):
        result = load_result("correlation_matrix.json")
        matrix = result["matrix"]
        n = len(matrix)
        for i in range(n):
            for j in range(i + 1, n):
                assert abs(matrix[i][j] - matrix[j][i]) < TOL_EXACT, \
                    f"Matrix not symmetric at [{i}][{j}]: {matrix[i][j]} vs {matrix[j][i]}"

    def test_correlation_range(self):
        result = load_result("correlation_matrix.json")
        matrix = result["matrix"]
        for i, row in enumerate(matrix):
            for j, val in enumerate(row):
                assert -1.0 - TOL_EXACT <= val <= 1.0 + TOL_EXACT, \
                    f"Correlation out of range at [{i}][{j}]: {val}"

    def test_correlation_methods_present(self):
        result = load_result("correlation_matrix.json")
        methods = result["methods"]
        required = {"brier", "log_score", "crra_0", "crra_1", "bt_skill"}
        actual = set(methods)
        assert required == actual, f"Expected methods {required}, got {actual}"


class TestRankings:
    def test_rankings_structure(self):
        result = load_result("rankings.json")
        required_methods = {"brier", "log_score", "crra_0", "crra_1", "bt_skill"}
        for method in required_methods:
            assert method in result, f"Missing ranking method: {method}"
            assert isinstance(result[method], list), f"Ranking for {method} should be a list"

    def test_rankings_complete(self):
        data = load_data()
        result = load_result("rankings.json")
        expected_fids = set(data["problems"][0]["forecasts"].keys())
        for method, ranking in result.items():
            assert set(ranking) == expected_fids, \
                f"Ranking for {method} has wrong forecasters: {set(ranking)} vs {expected_fids}"

    def test_brier_ranking_consistent(self):
        brier = load_result("brier_scores.json")
        rankings = load_result("rankings.json")
        expected = get_ranking(brier)
        assert rankings["brier"] == expected, \
            f"Brier ranking inconsistent with scores: {rankings['brier']} vs {expected}"

    def test_log_score_ranking_consistent(self):
        log_scores = load_result("log_scores.json")
        rankings = load_result("rankings.json")
        expected = get_ranking(log_scores)
        assert rankings["log_score"] == expected, \
            f"Log score ranking inconsistent: {rankings['log_score']} vs {expected}"

    def test_crra0_ranking_consistent(self):
        crra = load_result("crra_returns.json")
        rankings = load_result("rankings.json")
        scores = {fid: vals["gamma_0"] for fid, vals in crra.items()}
        expected = get_ranking(scores)
        assert rankings["crra_0"] == expected, \
            f"CRRA gamma=0 ranking inconsistent: {rankings['crra_0']} vs {expected}"

    def test_crra1_ranking_consistent(self):
        crra = load_result("crra_returns.json")
        rankings = load_result("rankings.json")
        scores = {fid: vals["gamma_1"] for fid, vals in crra.items()}
        expected = get_ranking(scores)
        assert rankings["crra_1"] == expected, \
            f"CRRA gamma=1 ranking inconsistent: {rankings['crra_1']} vs {expected}"
