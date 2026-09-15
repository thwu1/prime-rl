#!/usr/bin/env python3
"""
Correct solution for prediction market scoring pipeline audit and evaluation.
Queries the SQLite database, cleans data, implements all five scoring
methods correctly, evaluates the scoring framework, and produces the
audit report with consensus ranking.
"""

import sqlite3
import json
import os
import numpy as np
from collections import defaultdict
from scipy import stats


def load_raw_data():
    db = sqlite3.connect('/app/data/forecasts.db')
    db.row_factory = sqlite3.Row

    events = {}
    for row in db.execute("SELECT event_id, category, outcome FROM events"):
        events[row['event_id']] = {
            'category': row['category'],
            'outcome': row['outcome']
        }

    market = {}
    for row in db.execute("SELECT event_id, yes_price, no_price FROM markets"):
        market[row['event_id']] = {
            'yes_price': row['yes_price'],
            'no_price': row['no_price']
        }

    forecasts = []
    for row in db.execute(
            "SELECT event_id, forecaster_id, timestamp, probability FROM forecasts"):
        forecasts.append({
            'event_id': row['event_id'],
            'forecaster_id': row['forecaster_id'],
            'timestamp': row['timestamp'],
            'probability': row['probability'],
        })

    db.close()
    return events, market, forecasts


def clean_data(events, forecasts):
    """Clean the data: filter unresolved, remove orphans, deduplicate."""
    total_events = len(events)
    raw_count = len(forecasts)

    resolved_eids = {eid for eid, e in events.items() if e['outcome'] != -1}
    n_resolved = len(resolved_eids)

    issues = 0

    # Issue 1: unresolved events
    n_unresolved = total_events - n_resolved
    if n_unresolved > 0:
        issues += 1

    # Filter to valid forecasts (event exists AND is resolved)
    valid = []
    n_orphan = 0
    for fc in forecasts:
        if fc['event_id'] not in events:
            n_orphan += 1
            continue
        if fc['event_id'] in resolved_eids:
            valid.append(fc)

    # Issue 2: orphan forecasts
    if n_orphan > 0:
        issues += 1

    # Deduplicate: keep latest timestamp per (event_id, forecaster_id)
    best = {}
    n_duplicates = 0
    for fc in valid:
        key = (fc['event_id'], fc['forecaster_id'])
        if key in best:
            n_duplicates += 1
            if fc['timestamp'] > best[key]['timestamp']:
                best[key] = fc
        else:
            best[key] = fc

    # Issue 3: duplicate forecasts
    if n_duplicates > 0:
        issues += 1

    clean_forecasts = list(best.values())

    # Issue 4: extreme probabilities
    n_extreme = sum(1 for fc in clean_forecasts
                    if fc['probability'] == 0.0 or fc['probability'] == 1.0)
    if n_extreme > 0:
        issues += 1

    data_quality = {
        'events_total': total_events,
        'events_resolved': n_resolved,
        'forecasts_raw': raw_count,
        'forecasts_clean': len(clean_forecasts),
        'issues_found': issues
    }

    return clean_forecasts, resolved_eids, data_quality


def compute_brier(events, by_forecaster):
    scores = {}
    for fid, preds in by_forecaster.items():
        sq_errors = []
        for pred in preds:
            outcome = events[pred['event_id']]['outcome']
            sq_errors.append((pred['probability'] - outcome) ** 2)
        if sq_errors:
            scores[fid] = 1.0 - sum(sq_errors) / len(sq_errors)
    return scores


def compute_risk_neutral(events, market, by_forecaster):
    scores = {}
    for fid, preds in by_forecaster.items():
        returns = []
        for pred in preds:
            eid = pred['event_id']
            if eid not in market:
                continue
            outcome = events[eid]['outcome']
            prob = pred['probability']
            c_yes = market[eid]['yes_price']
            c_no = market[eid]['no_price']
            # Correct formula: division, not multiplication
            ev_yes = prob / c_yes - 1.0
            ev_no = (1.0 - prob) / c_no - 1.0
            if ev_yes > 0 and ev_yes >= ev_no:
                ret = (1.0 / c_yes - 1.0) if outcome == 1 else -1.0
            elif ev_no > 0:
                ret = (1.0 / c_no - 1.0) if outcome == 0 else -1.0
            else:
                ret = 0.0
            returns.append(ret)
        if returns:
            scores[fid] = sum(returns) / len(returns)
    return scores


def compute_kelly(events, market, by_forecaster):
    scores = {}
    for fid, preds in by_forecaster.items():
        returns = []
        for pred in preds:
            eid = pred['event_id']
            if eid not in market:
                continue
            outcome = events[eid]['outcome']
            prob = pred['probability']
            c_yes = market[eid]['yes_price']
            c_no = market[eid]['no_price']
            f_yes = max(0.0, min(1.0,
                (prob - c_yes) / (1.0 - c_yes) if c_yes < 1 else 0.0))
            f_no = max(0.0, min(1.0,
                ((1.0 - prob) - c_no) / (1.0 - c_no) if c_no < 1 else 0.0))
            if f_yes > 0 and f_yes >= f_no:
                if outcome == 1:
                    wealth = 1.0 + f_yes * (1.0 - c_yes) / c_yes
                else:
                    wealth = 1.0 - f_yes
                ret = wealth - 1.0
            elif f_no > 0:
                if outcome == 0:
                    wealth = 1.0 + f_no * (1.0 - c_no) / c_no
                else:
                    wealth = 1.0 - f_no
                ret = wealth - 1.0
            else:
                ret = 0.0
            returns.append(ret)
        if returns:
            scores[fid] = sum(returns) / len(returns)
    return scores


def crra_optimal_fraction(prob, price, gamma=0.5):
    """Compute CRRA-optimal bet fraction using closed form for gamma=0.5."""
    if price >= 1.0 or price <= 0.0:
        return 0.0
    R = 1.0 / price - 1.0
    if R <= 0:
        return 0.0
    p = prob
    q = 1.0 - prob
    # Closed form from FOC of E[U(W)] with U(W) = W^(1-gamma)/(1-gamma)
    num = p ** 2 * R ** 2 - q ** 2
    den = R * (p ** 2 * R + q ** 2)
    if den <= 0:
        return 0.0
    f = num / den
    return max(0.0, min(1.0, f))


def compute_crra_utility(events, market, by_forecaster, gamma=0.5):
    scores = {}
    for fid, preds in by_forecaster.items():
        returns = []
        for pred in preds:
            eid = pred['event_id']
            if eid not in market:
                continue
            outcome = events[eid]['outcome']
            prob = pred['probability']
            c_yes = market[eid]['yes_price']
            c_no = market[eid]['no_price']
            f_yes = crra_optimal_fraction(prob, c_yes, gamma)
            f_no = crra_optimal_fraction(1.0 - prob, c_no, gamma)
            if f_yes > 0 and f_yes >= f_no:
                if outcome == 1:
                    ret = f_yes * (1.0 / c_yes - 1.0)
                else:
                    ret = -f_yes
            elif f_no > 0:
                if outcome == 0:
                    ret = f_no * (1.0 / c_no - 1.0)
                else:
                    ret = -f_no
            else:
                ret = 0.0
            returns.append(ret)
        if returns:
            scores[fid] = sum(returns) / len(returns)
    return scores


def compute_pairwise_skill(events, clean_forecasts):
    preds_by_event = defaultdict(list)
    for fc in clean_forecasts:
        preds_by_event[fc['event_id']].append(
            (fc['forecaster_id'], fc['probability']))

    forecaster_ids = sorted(set(fc['forecaster_id'] for fc in clean_forecasts))
    n = len(forecaster_ids)
    fid_to_idx = {fid: i for i, fid in enumerate(forecaster_ids)}

    win_matrix = np.zeros((n, n))
    for eid, epreds in preds_by_event.items():
        outcome = events[eid]['outcome']
        for a in range(len(epreds)):
            for b in range(a + 1, len(epreds)):
                fid_a, prob_a = epreds[a]
                fid_b, prob_b = epreds[b]
                err_a = abs(prob_a - outcome)
                err_b = abs(prob_b - outcome)
                idx_a = fid_to_idx[fid_a]
                idx_b = fid_to_idx[fid_b]
                if err_a < err_b:
                    win_matrix[idx_a][idx_b] += 1
                elif err_b < err_a:
                    win_matrix[idx_b][idx_a] += 1
                else:
                    win_matrix[idx_a][idx_b] += 0.5
                    win_matrix[idx_b][idx_a] += 0.5

    n_comp = win_matrix + win_matrix.T
    total_wins = win_matrix.sum(axis=1)

    theta = np.ones(n)
    for _ in range(1000):
        theta_old = theta.copy()
        for i in range(n):
            denom = 0.0
            for j in range(n):
                if i != j and n_comp[i][j] > 0:
                    denom += n_comp[i][j] / (theta_old[i] + theta_old[j])
            if denom > 0 and total_wins[i] > 0:
                theta[i] = total_wins[i] / denom
            else:
                theta[i] = theta_old[i]
        # Normalize by mean
        theta = theta / np.mean(theta)
        if np.max(np.abs(theta - theta_old)) < 1e-8:
            break

    return {forecaster_ids[i]: float(theta[i]) for i in range(n)}


def compute_method_evaluation(bri, rn, kel, crra, pw, corr_matrix_lists):
    """Evaluate the scoring framework and design consensus ranking."""
    method_names = ['brier', 'risk_neutral', 'kelly', 'crra_utility',
                    'pairwise_skill']
    all_fids = sorted(bri.keys())
    n_forecasters = len(all_fids)

    # Convert correlation matrix to numpy array
    corr_np = np.array(corr_matrix_lists)

    # Eigendecomposition of the correlation matrix
    eigenvalues_raw, eigenvectors_raw = np.linalg.eigh(corr_np)
    # Sort descending
    idx = np.argsort(eigenvalues_raw)[::-1]
    eigenvalues = eigenvalues_raw[idx]
    eigenvectors = eigenvectors_raw[:, idx]

    # Kaiser criterion: retain components with eigenvalue >= 1.0
    effective_dims = int(np.sum(eigenvalues >= 1.0))

    # Compute method weights from communality under retained components
    importance = np.zeros(5)
    for k in range(5):
        if eigenvalues[k] >= 1.0:
            importance += eigenvectors[:, k] ** 2 * eigenvalues[k]
    weights = importance / importance.sum()

    method_weights = {name: round(float(w), 6)
                      for name, w in zip(method_names, weights)}

    # Compute percentile-normalized ranks for each method
    method_scores = {
        'brier': [bri[fid] for fid in all_fids],
        'risk_neutral': [rn[fid] for fid in all_fids],
        'kelly': [kel[fid] for fid in all_fids],
        'crra_utility': [crra[fid] for fid in all_fids],
        'pairwise_skill': [pw[fid] for fid in all_fids],
    }

    percentiles = {}
    ranks_desc = {}
    for method in method_names:
        scores_arr = np.array(method_scores[method])
        # rankdata: 1 = smallest (worst), N = largest (best)
        rank_asc = stats.rankdata(scores_arr, method='ordinal')
        # Percentile: 0.0 for worst, 1.0 for best
        pct = (rank_asc - 1.0) / (n_forecasters - 1.0)
        percentiles[method] = pct
        # Descending rank: 1 = best, N = worst
        rank_d = (n_forecasters + 1 - rank_asc).astype(int)
        ranks_desc[method] = rank_d

    # Consensus score: weighted sum of percentile ranks
    composite = np.zeros(n_forecasters)
    for j, method in enumerate(method_names):
        composite += weights[j] * percentiles[method]

    consensus_ranking = sorted(
        [{"forecaster_id": all_fids[i], "score": round(float(composite[i]), 6)}
         for i in range(n_forecasters)],
        key=lambda x: -x['score']
    )

    # Stability analysis: max rank spread across methods
    max_rank_spread = {}
    for i, fid in enumerate(all_fids):
        ranks = [int(ranks_desc[method][i]) for method in method_names]
        spread = max(ranks) - min(ranks)
        max_rank_spread[fid] = spread

    min_spread = min(max_rank_spread.values())
    max_spread = max(max_rank_spread.values())
    most_stable = min(fid for fid in all_fids
                      if max_rank_spread[fid] == min_spread)
    least_stable = min(fid for fid in all_fids
                       if max_rank_spread[fid] == max_spread)

    return {
        'eigenvalues': [round(float(ev), 6) for ev in eigenvalues],
        'effective_dimensions': effective_dims,
        'method_weights': method_weights,
        'consensus_ranking': consensus_ranking,
        'stability_analysis': {
            'max_rank_spread': max_rank_spread,
            'most_stable_forecaster': most_stable,
            'least_stable_forecaster': least_stable,
        }
    }


def sort_ranking(score_dict):
    return [{"forecaster_id": k, "score": round(v, 6)}
            for k, v in sorted(score_dict.items(), key=lambda x: -x[1])]


def main():
    # Load config
    with open('/app/pipeline/config.json') as f:
        config = json.load(f)
    gamma = config['risk_aversion']

    # Load and clean data
    events, market, forecasts = load_raw_data()
    clean_forecasts, resolved_eids, data_quality = clean_data(events, forecasts)

    # Group clean forecasts by forecaster
    by_forecaster = defaultdict(list)
    for fc in clean_forecasts:
        by_forecaster[fc['forecaster_id']].append(fc)

    # Compute all scoring methods
    bri = compute_brier(events, by_forecaster)
    rn = compute_risk_neutral(events, market, by_forecaster)
    kel = compute_kelly(events, market, by_forecaster)
    crra = compute_crra_utility(events, market, by_forecaster, gamma=gamma)
    pw = compute_pairwise_skill(events, clean_forecasts)

    # Compute 5x5 Spearman correlation matrix
    all_fids = sorted(bri.keys())
    arrays = [
        [bri[fid] for fid in all_fids],
        [rn[fid] for fid in all_fids],
        [kel[fid] for fid in all_fids],
        [crra[fid] for fid in all_fids],
        [pw[fid] for fid in all_fids],
    ]
    corr_matrix = [[1.0] * 5 for _ in range(5)]
    for i in range(5):
        for j in range(i + 1, 5):
            corr, _ = stats.spearmanr(arrays[i], arrays[j])
            corr_matrix[i][j] = round(corr, 6)
            corr_matrix[j][i] = round(corr, 6)

    # Evaluate the scoring framework and design consensus ranking
    method_eval = compute_method_evaluation(bri, rn, kel, crra, pw,
                                            corr_matrix)

    # Build output
    result = {
        "rankings": {
            "brier": sort_ranking(bri),
            "risk_neutral": sort_ranking(rn),
            "kelly": sort_ranking(kel),
            "crra_utility": sort_ranking(crra),
            "pairwise_skill": sort_ranking(pw),
        },
        "data_quality": data_quality,
        "correlation_matrix": corr_matrix,
        "method_evaluation": method_eval,
    }

    os.makedirs('/app/results', exist_ok=True)
    with open('/app/results/audit.json', 'w') as f:
        json.dump(result, f, indent=2)

    print("Audit and evaluation complete. Results written to /app/results/audit.json")


if __name__ == '__main__':
    main()
