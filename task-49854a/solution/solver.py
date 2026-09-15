#!/usr/bin/env python3

"""
Prediction market forecaster evaluation pipeline.
Loads scattered raw data, cleans quality issues, computes all scoring methods.
"""

import csv
import glob
import json
import math
import os
import numpy as np
from scipy.optimize import minimize_scalar
from scipy.stats import spearmanr


def load_and_consolidate_data():
    """Load raw data files, clean anomalies, and build unified dataset."""
    # 1. Load events from JSONL
    events = {}
    with open("/app/raw/events.jsonl") as f:
        for line in f:
            line = line.strip()
            if line:
                ev = json.loads(line)
                events[ev["event_id"]] = ev

    # 2. Load outcomes from CSV (keyed by title, not event ID)
    outcomes_by_title = {}
    with open("/app/raw/outcomes.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            outcomes_by_title[row["title"].strip()] = row["outcome"].strip()

    # 3. Load per-forecaster JSON files, handling anomalies
    forecasters = {}
    forecast_dir = "/app/raw/forecasts"
    for filepath in sorted(glob.glob(os.path.join(forecast_dir, "*.json"))):
        with open(filepath) as f:
            data = json.load(f)
        fid = data["forecaster_id"]
        preds = {}
        for pred in data["predictions"]:
            eid = pred["event_id"]
            # Handle variant key names ("prob" vs "probability")
            prob = pred.get("probability", pred.get("prob"))
            if prob is None:
                continue
            # Detect and normalize percentage values (>1.0 means percentages)
            if prob > 1.0:
                prob = prob / 100.0
            # Deduplicate: keep first occurrence per event
            if eid not in preds:
                preds[eid] = prob
        forecasters[fid] = preds

    # 4. Consolidate: join events with outcomes on title
    problems = []
    for eid in sorted(events.keys()):
        ev = events[eid]
        title = ev["title"]
        outcome = outcomes_by_title.get(title)
        if outcome is None:
            continue
        forecasts = {}
        for fid in sorted(forecasters.keys()):
            if eid in forecasters[fid]:
                forecasts[fid] = forecasters[fid][eid]
        problems.append({
            "id": eid,
            "title": title,
            "market_price_yes": ev["market_close_prob"],
            "resolution": outcome,
            "forecasts": forecasts,
        })

    return {"problems": problems}


def compute_brier_scores(data):
    """Quadratic proper scoring rule: 1 - mean(squared error)."""
    scores = {}
    for problem in data["problems"]:
        outcome = 1.0 if problem["resolution"] == "Yes" else 0.0
        for fid, p_yes in problem["forecasts"].items():
            brier = (p_yes - outcome) ** 2
            scores.setdefault(fid, []).append(brier)
    return {fid: 1.0 - float(np.mean(vals)) for fid, vals in scores.items()}


def compute_log_scores(data):
    """Logarithmic proper scoring rule: mean log(p_correct)."""
    scores = {}
    for problem in data["problems"]:
        res = problem["resolution"]
        for fid, p_yes in problem["forecasts"].items():
            p_correct = p_yes if res == "Yes" else 1.0 - p_yes
            scores.setdefault(fid, []).append(math.log(max(p_correct, 1e-15)))
    return {fid: float(np.mean(vals)) for fid, vals in scores.items()}


def _crra_return_gamma0(p, q, resolution):
    """Risk-neutral (all-in) return."""
    if p > q:
        return (1.0 / q - 1.0) if resolution == "Yes" else -1.0
    elif p < q:
        return (1.0 / (1.0 - q) - 1.0) if resolution == "No" else -1.0
    else:
        return 0.0


def _crra_return_gamma1(p, q, resolution):
    """Kelly criterion (log utility) return."""
    if p > q:
        alpha = (p - q) / (1.0 - q)
        return alpha * (1.0 - q) / q if resolution == "Yes" else -alpha
    elif p < q:
        alpha = (q - p) / q
        return alpha * q / (1.0 - q) if resolution == "No" else -alpha
    else:
        return 0.0


def _crra_return_gamma05(p, q, resolution):
    """CRRA gamma=0.5 optimal return via numerical optimization."""
    gamma = 0.5

    def neg_eu_yes(alpha):
        w_win = 1.0 + alpha * (1.0 - q) / q
        w_lose = 1.0 - alpha
        if w_win <= 1e-12 or w_lose <= 1e-12:
            return 1e10
        return -(p * w_win ** (1 - gamma) / (1 - gamma) +
                 (1 - p) * w_lose ** (1 - gamma) / (1 - gamma))

    def neg_eu_no(alpha):
        w_win = 1.0 + alpha * q / (1.0 - q)
        w_lose = 1.0 - alpha
        if w_win <= 1e-12 or w_lose <= 1e-12:
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
        return alpha * (1.0 - q) / q if resolution == "Yes" else -alpha
    elif eu_no > eu_yes and eu_no > eu_notrade + 1e-12:
        alpha = alpha_no
        return alpha * q / (1.0 - q) if resolution == "No" else -alpha
    else:
        return 0.0


def compute_crra_returns(data):
    """CRRA optimal returns at gamma=0, 0.5, 1 for each forecaster."""
    results = {}
    forecaster_ids = sorted(set(
        fid for p in data["problems"] for fid in p["forecasts"]
    ))
    for fid in forecaster_ids:
        g0, g05, g1 = [], [], []
        for problem in data["problems"]:
            if fid not in problem["forecasts"]:
                continue
            p = problem["forecasts"][fid]
            q = problem["market_price_yes"]
            res = problem["resolution"]
            g0.append(_crra_return_gamma0(p, q, res))
            g1.append(_crra_return_gamma1(p, q, res))
            g05.append(_crra_return_gamma05(p, q, res))
        results[fid] = {
            "gamma_0": float(np.mean(g0)),
            "gamma_0.5": float(np.mean(g05)),
            "gamma_1": float(np.mean(g1)),
        }
    return results


def compute_bt_skills(data):
    """Bradley-Terry skill estimation via iterative MLE."""
    forecaster_ids = sorted(set(
        fid for p in data["problems"] for fid in p["forecasts"]
    ))
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
        for i in range(len(fids)):
            for j in range(i + 1, len(fids)):
                fi, fj = fids[i], fids[j]
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
    for _ in range(5000):
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
    return {forecaster_ids[i]: float(theta[i]) for i in range(n)}


def compute_correlation_matrix(brier, log_scores, crra, bt):
    """Spearman rank correlation matrix across scoring methods."""
    forecaster_ids = sorted(brier.keys())
    score_vectors = {
        "brier": [brier[fid] for fid in forecaster_ids],
        "log_score": [log_scores[fid] for fid in forecaster_ids],
        "crra_0": [crra[fid]["gamma_0"] for fid in forecaster_ids],
        "crra_1": [crra[fid]["gamma_1"] for fid in forecaster_ids],
        "bt_skill": [bt[fid] for fid in forecaster_ids],
    }
    methods = ["brier", "log_score", "crra_0", "crra_1", "bt_skill"]
    n = len(methods)
    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                matrix[i][j] = 1.0
            else:
                rho, _ = spearmanr(score_vectors[methods[i]], score_vectors[methods[j]])
                matrix[i][j] = float(rho)
    return {"methods": methods, "matrix": matrix}


def compute_rankings(brier, log_scores, crra, bt):
    """Rank forecasters best-to-worst under each method."""
    def rank_desc(scores):
        return sorted(scores.keys(), key=lambda k: scores[k], reverse=True)
    return {
        "brier": rank_desc(brier),
        "log_score": rank_desc(log_scores),
        "crra_0": rank_desc({fid: crra[fid]["gamma_0"] for fid in crra}),
        "crra_1": rank_desc({fid: crra[fid]["gamma_1"] for fid in crra}),
        "bt_skill": rank_desc(bt),
    }


def main():
    data = load_and_consolidate_data()
    brier = compute_brier_scores(data)
    log_scores = compute_log_scores(data)
    crra = compute_crra_returns(data)
    bt = compute_bt_skills(data)
    corr = compute_correlation_matrix(brier, log_scores, crra, bt)
    rankings = compute_rankings(brier, log_scores, crra, bt)

    os.makedirs("/app/results", exist_ok=True)
    outputs = {
        "brier_scores.json": brier,
        "log_scores.json": log_scores,
        "crra_returns.json": crra,
        "bt_skills.json": bt,
        "correlation_matrix.json": corr,
        "rankings.json": rankings,
    }
    for filename, content in outputs.items():
        with open(f"/app/results/{filename}", "w") as f:
            json.dump(content, f, indent=2)
    print("All results written to /app/results/")


if __name__ == "__main__":
    main()
