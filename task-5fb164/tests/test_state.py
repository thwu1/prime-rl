"""Tests for prediction market scoring pipeline audit and evaluation."""

import json
import sqlite3
import os
import numpy as np
from collections import defaultdict
from scipy import stats
import pytest


# ============================================================
# Data loading from SQLite
# ============================================================

def load_raw_data():
    """Load all raw data from the SQLite database."""
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


def clean_data(events, market, forecasts):
    """Apply correct cleaning: filter unresolved, deduplicate, remove orphans."""
    resolved_eids = {eid for eid, e in events.items() if e['outcome'] != -1}

    valid = [fc for fc in forecasts if fc['event_id'] in resolved_eids]

    best = {}
    for fc in valid:
        key = (fc['event_id'], fc['forecaster_id'])
        if key not in best or fc['timestamp'] > best[key]['timestamp']:
            best[key] = fc

    clean_forecasts = list(best.values())

    by_forecaster = defaultdict(list)
    for fc in clean_forecasts:
        by_forecaster[fc['forecaster_id']].append(fc)

    return resolved_eids, clean_forecasts, by_forecaster


def count_raw_forecasts():
    """Count total rows in forecasts table."""
    db = sqlite3.connect('/app/data/forecasts.db')
    count = db.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0]
    db.close()
    return count


# ============================================================
# Reference scoring implementations
# ============================================================

def ref_brier(events, by_forecaster):
    scores = {}
    for fid, preds in by_forecaster.items():
        sq_errors = []
        for pred in preds:
            outcome = events[pred['event_id']]['outcome']
            sq_errors.append((pred['probability'] - outcome) ** 2)
        if sq_errors:
            scores[fid] = 1.0 - sum(sq_errors) / len(sq_errors)
    return scores


def ref_risk_neutral(events, market, by_forecaster):
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


def ref_kelly(events, market, by_forecaster):
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
    num = p ** 2 * R ** 2 - q ** 2
    den = R * (p ** 2 * R + q ** 2)
    if den <= 0:
        return 0.0
    f = num / den
    return max(0.0, min(1.0, f))


def ref_crra_utility(events, market, by_forecaster, gamma=0.5):
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


def ref_pairwise_skill(events, clean_forecasts):
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
        theta = theta / np.mean(theta)
        if np.max(np.abs(theta - theta_old)) < 1e-8:
            break

    return {forecaster_ids[i]: float(theta[i]) for i in range(n)}


def compute_ref_correlation(bri, rn, kel, crra, pw):
    """Compute 5x5 Spearman correlation matrix."""
    all_fids = sorted(bri.keys())
    arrays = [
        [bri[fid] for fid in all_fids],
        [rn[fid] for fid in all_fids],
        [kel[fid] for fid in all_fids],
        [crra[fid] for fid in all_fids],
        [pw[fid] for fid in all_fids],
    ]
    matrix = np.ones((5, 5))
    for i in range(5):
        for j in range(i + 1, 5):
            corr, _ = stats.spearmanr(arrays[i], arrays[j])
            matrix[i][j] = corr
            matrix[j][i] = corr
    return matrix


def compute_ref_method_evaluation(bri, rn, kel, crra, pw, corr_matrix):
    """Compute reference method evaluation metrics."""
    method_names = ['brier', 'risk_neutral', 'kelly', 'crra_utility',
                    'pairwise_skill']
    all_fids = sorted(bri.keys())
    n_forecasters = len(all_fids)

    corr_np = np.array(corr_matrix)

    eigenvalues_raw, eigenvectors_raw = np.linalg.eigh(corr_np)
    idx = np.argsort(eigenvalues_raw)[::-1]
    eigenvalues = eigenvalues_raw[idx]
    eigenvectors = eigenvectors_raw[:, idx]

    effective_dims = int(np.sum(eigenvalues >= 1.0))

    importance = np.zeros(5)
    for k in range(5):
        if eigenvalues[k] >= 1.0:
            importance += eigenvectors[:, k] ** 2 * eigenvalues[k]
    weights = importance / importance.sum()

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
        rank_asc = stats.rankdata(scores_arr, method='ordinal')
        pct = (rank_asc - 1.0) / (n_forecasters - 1.0)
        percentiles[method] = pct
        rank_d = (n_forecasters + 1 - rank_asc).astype(int)
        ranks_desc[method] = rank_d

    composite = np.zeros(n_forecasters)
    for j, method in enumerate(method_names):
        composite += weights[j] * percentiles[method]

    consensus_scores = {all_fids[i]: float(composite[i])
                        for i in range(n_forecasters)}

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
        'eigenvalues': eigenvalues,
        'effective_dimensions': effective_dims,
        'weights': {name: float(w) for name, w in zip(method_names, weights)},
        'consensus_scores': consensus_scores,
        'max_rank_spread': max_rank_spread,
        'most_stable': most_stable,
        'least_stable': least_stable,
    }


# ============================================================
# Precompute reference answers
# ============================================================

@pytest.fixture(scope="session")
def ref_data():
    events, market, forecasts = load_raw_data()
    resolved_eids, clean_forecasts, by_forecaster = clean_data(
        events, market, forecasts)

    bri = ref_brier(events, by_forecaster)
    rn = ref_risk_neutral(events, market, by_forecaster)
    kel = ref_kelly(events, market, by_forecaster)
    crra = ref_crra_utility(events, market, by_forecaster, gamma=0.5)
    pw = ref_pairwise_skill(events, clean_forecasts)
    corr = compute_ref_correlation(bri, rn, kel, crra, pw)
    meval = compute_ref_method_evaluation(bri, rn, kel, crra, pw, corr)

    raw_count = count_raw_forecasts()

    return {
        'events': events,
        'market': market,
        'raw_count': raw_count,
        'resolved_eids': resolved_eids,
        'clean_forecasts': clean_forecasts,
        'by_forecaster': by_forecaster,
        'brier': bri,
        'risk_neutral': rn,
        'kelly': kel,
        'crra_utility': crra,
        'pairwise_skill': pw,
        'correlation': corr,
        'method_eval': meval,
    }


def load_results():
    with open('/app/results/audit.json') as f:
        return json.load(f)


def load_baseline():
    with open('/app/baseline/results.json') as f:
        return json.load(f)


# ============================================================
# Structure tests
# ============================================================

class TestStructure:
    def test_output_exists(self):
        assert os.path.exists('/app/results/audit.json'), \
            "audit.json not found at /app/results/"

    def test_required_top_keys(self):
        results = load_results()
        for key in ['rankings', 'data_quality', 'correlation_matrix',
                     'method_evaluation']:
            assert key in results, f"Missing top-level key: {key}"

    def test_ranking_methods_present(self):
        results = load_results()
        for method in ['brier', 'risk_neutral', 'kelly',
                       'crra_utility', 'pairwise_skill']:
            assert method in results['rankings'], \
                f"Missing ranking method: {method}"

    def test_ranking_format(self):
        results = load_results()
        for method in ['brier', 'risk_neutral', 'kelly',
                       'crra_utility', 'pairwise_skill']:
            ranking = results['rankings'][method]
            assert isinstance(ranking, list), f"{method} should be a list"
            assert len(ranking) == 25, \
                f"{method} should have 25 entries, got {len(ranking)}"
            for entry in ranking:
                assert 'forecaster_id' in entry, \
                    f"Missing forecaster_id in {method}"
                assert 'score' in entry, f"Missing score in {method}"

    def test_rankings_sorted_descending(self):
        results = load_results()
        for method in ['brier', 'risk_neutral', 'kelly',
                       'crra_utility', 'pairwise_skill']:
            ranking = results['rankings'][method]
            scores = [e['score'] for e in ranking]
            for i in range(len(scores) - 1):
                assert scores[i] >= scores[i + 1] - 1e-9, \
                    f"{method} not sorted descending at index {i}"

    def test_all_forecasters_present(self):
        results = load_results()
        expected_ids = {f"FC{i:03d}" for i in range(1, 26)}
        for method in ['brier', 'risk_neutral', 'kelly',
                       'crra_utility', 'pairwise_skill']:
            actual_ids = {e['forecaster_id']
                          for e in results['rankings'][method]}
            assert actual_ids == expected_ids, \
                f"{method}: forecaster IDs mismatch. " \
                f"Missing: {expected_ids - actual_ids}, " \
                f"Extra: {actual_ids - expected_ids}"

    def test_data_quality_fields(self):
        results = load_results()
        dq = results['data_quality']
        for field in ['events_total', 'events_resolved', 'forecasts_raw',
                      'forecasts_clean', 'issues_found']:
            assert field in dq, f"Missing data_quality field: {field}"

    def test_correlation_matrix_shape(self):
        results = load_results()
        matrix = results['correlation_matrix']
        assert len(matrix) == 5, "Correlation matrix should be 5x5"
        for row in matrix:
            assert len(row) == 5, "Each row should have 5 elements"

    def test_method_evaluation_structure(self):
        results = load_results()
        me = results['method_evaluation']
        for key in ['eigenvalues', 'effective_dimensions', 'method_weights',
                     'consensus_ranking', 'stability_analysis']:
            assert key in me, f"Missing method_evaluation key: {key}"

    def test_method_evaluation_eigenvalues_format(self):
        results = load_results()
        evs = results['method_evaluation']['eigenvalues']
        assert isinstance(evs, list) and len(evs) == 5, \
            "eigenvalues must be a list of 5 values"

    def test_method_evaluation_weights_format(self):
        results = load_results()
        mw = results['method_evaluation']['method_weights']
        for method in ['brier', 'risk_neutral', 'kelly',
                       'crra_utility', 'pairwise_skill']:
            assert method in mw, f"Missing weight for {method}"

    def test_consensus_ranking_format(self):
        results = load_results()
        cr = results['method_evaluation']['consensus_ranking']
        assert isinstance(cr, list) and len(cr) == 25, \
            "consensus_ranking must have 25 entries"
        for entry in cr:
            assert 'forecaster_id' in entry and 'score' in entry

    def test_consensus_ranking_sorted(self):
        results = load_results()
        cr = results['method_evaluation']['consensus_ranking']
        scores = [e['score'] for e in cr]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1] - 1e-9, \
                f"consensus_ranking not sorted descending at index {i}"

    def test_stability_analysis_structure(self):
        results = load_results()
        sa = results['method_evaluation']['stability_analysis']
        assert 'max_rank_spread' in sa
        assert 'most_stable_forecaster' in sa
        assert 'least_stable_forecaster' in sa
        assert len(sa['max_rank_spread']) == 25


# ============================================================
# Data quality tests
# ============================================================

class TestDataQuality:
    def test_events_total(self, ref_data):
        results = load_results()
        assert results['data_quality']['events_total'] == 200, \
            f"events_total should be 200"

    def test_events_resolved(self, ref_data):
        results = load_results()
        expected = len(ref_data['resolved_eids'])
        actual = results['data_quality']['events_resolved']
        assert actual == expected, \
            f"events_resolved should be {expected}, got {actual}"

    def test_forecasts_raw(self, ref_data):
        results = load_results()
        expected = ref_data['raw_count']
        actual = results['data_quality']['forecasts_raw']
        assert actual == expected, \
            f"forecasts_raw should be {expected}, got {actual}"

    def test_forecasts_clean(self, ref_data):
        results = load_results()
        expected = len(ref_data['clean_forecasts'])
        actual = results['data_quality']['forecasts_clean']
        assert actual == expected, \
            f"forecasts_clean should be {expected}, got {actual}"

    def test_issues_found(self):
        results = load_results()
        assert results['data_quality']['issues_found'] >= 3, \
            f"Should identify at least 3 data quality issues, " \
            f"got {results['data_quality']['issues_found']}"


# ============================================================
# Brier (calibration) score tests
# ============================================================

class TestBrier:
    def test_brier_scores(self, ref_data):
        results = load_results()
        expected = ref_data['brier']
        for entry in results['rankings']['brier']:
            fid = entry['forecaster_id']
            assert fid in expected, f"Unknown forecaster: {fid}"
            assert abs(expected[fid] - entry['score']) < 1e-4, \
                f"Brier mismatch for {fid}: " \
                f"expected {expected[fid]:.6f}, got {entry['score']}"

    def test_brier_range(self):
        results = load_results()
        for entry in results['rankings']['brier']:
            assert 0 <= entry['score'] <= 1, \
                f"Brier out of range for {entry['forecaster_id']}"

    def test_brier_top3(self, ref_data):
        expected = ref_data['brier']
        top3_exp = [x[0] for x in sorted(
            expected.items(), key=lambda x: -x[1])[:3]]
        results = load_results()
        top3_act = [e['forecaster_id']
                    for e in results['rankings']['brier'][:3]]
        assert top3_act == top3_exp, \
            f"Brier top-3 mismatch: expected {top3_exp}, got {top3_act}"


# ============================================================
# Risk-neutral return tests
# ============================================================

class TestRiskNeutral:
    def test_risk_neutral_scores(self, ref_data):
        results = load_results()
        expected = ref_data['risk_neutral']
        for entry in results['rankings']['risk_neutral']:
            fid = entry['forecaster_id']
            assert fid in expected, f"Unknown forecaster: {fid}"
            assert abs(expected[fid] - entry['score']) < 1e-4, \
                f"Risk-neutral mismatch for {fid}: " \
                f"expected {expected[fid]:.6f}, got {entry['score']}"

    def test_risk_neutral_has_variation(self):
        """Correct risk-neutral returns should NOT all be near zero."""
        results = load_results()
        scores = [e['score'] for e in results['rankings']['risk_neutral']]
        score_range = max(scores) - min(scores)
        assert score_range > 0.05, \
            f"Risk-neutral scores have suspiciously low variation " \
            f"(range={score_range:.4f}). Check EV formula."

    def test_risk_neutral_top3(self, ref_data):
        expected = ref_data['risk_neutral']
        top3_exp = [x[0] for x in sorted(
            expected.items(), key=lambda x: -x[1])[:3]]
        results = load_results()
        top3_act = [e['forecaster_id']
                    for e in results['rankings']['risk_neutral'][:3]]
        assert top3_act == top3_exp, \
            f"Risk-neutral top-3 mismatch: expected {top3_exp}, got {top3_act}"

    def test_risk_neutral_differs_from_baseline(self):
        """Corrected results must differ from buggy baseline."""
        results = load_results()
        baseline = load_baseline()
        result_scores = {e['forecaster_id']: e['score']
                         for e in results['rankings']['risk_neutral']}
        baseline_scores = {e['forecaster_id']: e['score']
                           for e in baseline['risk_neutral']}
        diffs = [abs(result_scores[fid] - baseline_scores.get(fid, 0))
                 for fid in result_scores]
        max_diff = max(diffs)
        assert max_diff > 0.01, \
            "Risk-neutral results should differ significantly from baseline"


# ============================================================
# Kelly return tests
# ============================================================

class TestKelly:
    def test_kelly_scores(self, ref_data):
        results = load_results()
        expected = ref_data['kelly']
        for entry in results['rankings']['kelly']:
            fid = entry['forecaster_id']
            assert fid in expected, f"Unknown forecaster: {fid}"
            assert abs(expected[fid] - entry['score']) < 1e-4, \
                f"Kelly mismatch for {fid}: " \
                f"expected {expected[fid]:.6f}, got {entry['score']}"

    def test_kelly_bounded(self):
        results = load_results()
        for entry in results['rankings']['kelly']:
            assert entry['score'] >= -1.0 - 1e-9, \
                f"Kelly return below -1 for {entry['forecaster_id']}"

    def test_kelly_top3(self, ref_data):
        expected = ref_data['kelly']
        top3_exp = [x[0] for x in sorted(
            expected.items(), key=lambda x: -x[1])[:3]]
        results = load_results()
        top3_act = [e['forecaster_id']
                    for e in results['rankings']['kelly'][:3]]
        assert top3_act == top3_exp, \
            f"Kelly top-3 mismatch: expected {top3_exp}, got {top3_act}"


# ============================================================
# CRRA utility return tests
# ============================================================

class TestCRRAUtility:
    def test_crra_scores(self, ref_data):
        results = load_results()
        expected = ref_data['crra_utility']
        for entry in results['rankings']['crra_utility']:
            fid = entry['forecaster_id']
            assert fid in expected, f"Unknown forecaster: {fid}"
            assert abs(expected[fid] - entry['score']) < 1e-3, \
                f"CRRA utility mismatch for {fid}: " \
                f"expected {expected[fid]:.6f}, got {entry['score']}"

    def test_crra_not_all_zero(self):
        """CRRA utility scores must not all be zero (stub detection)."""
        results = load_results()
        scores = [e['score'] for e in results['rankings']['crra_utility']]
        nonzero = sum(1 for s in scores if abs(s) > 1e-6)
        assert nonzero > 20, \
            f"Only {nonzero}/25 CRRA scores are non-zero. " \
            f"CRRA utility was not properly implemented."

    def test_crra_has_variation(self):
        results = load_results()
        scores = [e['score'] for e in results['rankings']['crra_utility']]
        score_range = max(scores) - min(scores)
        assert score_range > 0.01, \
            f"CRRA scores have suspiciously low variation " \
            f"(range={score_range:.6f})."

    def test_crra_top3(self, ref_data):
        expected = ref_data['crra_utility']
        top3_exp = [x[0] for x in sorted(
            expected.items(), key=lambda x: -x[1])[:3]]
        results = load_results()
        top3_act = [e['forecaster_id']
                    for e in results['rankings']['crra_utility'][:3]]
        assert top3_act == top3_exp, \
            f"CRRA utility top-3 mismatch: expected {top3_exp}, got {top3_act}"

    def test_crra_differs_from_baseline(self):
        """CRRA must differ from baseline (which is all zeros)."""
        results = load_results()
        baseline = load_baseline()
        result_scores = {e['forecaster_id']: e['score']
                         for e in results['rankings']['crra_utility']}
        baseline_scores = {e['forecaster_id']: e['score']
                           for e in baseline['crra_utility']}
        diffs = [abs(result_scores[fid] - baseline_scores.get(fid, 0))
                 for fid in result_scores]
        max_diff = max(diffs)
        assert max_diff > 0.01, \
            "CRRA results should differ from baseline (baseline is stub zeros)"

    def test_crra_between_kelly_and_risk_neutral(self, ref_data):
        """CRRA gamma=0.5 bet sizes should fall between Kelly and risk-neutral,
        so the return variance should be between the two."""
        results = load_results()
        crra_scores = [e['score']
                       for e in results['rankings']['crra_utility']]
        kelly_scores = [e['score']
                        for e in results['rankings']['kelly']]
        crra_var = np.var(crra_scores)
        kelly_var = np.var(kelly_scores)
        assert crra_var > kelly_var * 0.5, \
            f"CRRA variance ({crra_var:.6f}) seems too low relative to " \
            f"Kelly variance ({kelly_var:.6f})"


# ============================================================
# Pairwise skill tests
# ============================================================

class TestPairwiseSkill:
    def test_pairwise_all_positive(self):
        results = load_results()
        for entry in results['rankings']['pairwise_skill']:
            assert entry['score'] > 0, \
                f"Pairwise skill non-positive for {entry['forecaster_id']}"

    def test_pairwise_scores(self, ref_data):
        results = load_results()
        expected = ref_data['pairwise_skill']
        for entry in results['rankings']['pairwise_skill']:
            fid = entry['forecaster_id']
            assert fid in expected, f"Unknown forecaster: {fid}"
            assert abs(expected[fid] - entry['score']) < 0.02, \
                f"Pairwise skill mismatch for {fid}: " \
                f"expected {expected[fid]:.4f}, got {entry['score']}"

    def test_pairwise_top3(self, ref_data):
        expected = ref_data['pairwise_skill']
        top3_exp = [x[0] for x in sorted(
            expected.items(), key=lambda x: -x[1])[:3]]
        results = load_results()
        top3_act = [e['forecaster_id']
                    for e in results['rankings']['pairwise_skill'][:3]]
        assert top3_act == top3_exp, \
            f"Pairwise skill top-3 mismatch: expected {top3_exp}, got {top3_act}"

    def test_pairwise_normalized(self):
        """Skill parameters should be mean-normalized (mean ~ 1)."""
        results = load_results()
        scores = [e['score']
                  for e in results['rankings']['pairwise_skill']]
        mean_score = sum(scores) / len(scores)
        assert abs(mean_score - 1.0) < 0.05, \
            f"Pairwise skill mean should be ~1.0, got {mean_score:.4f}"


# ============================================================
# Correlation matrix tests
# ============================================================

class TestCorrelation:
    def test_diagonal_ones(self):
        results = load_results()
        matrix = results['correlation_matrix']
        for i in range(5):
            assert abs(matrix[i][i] - 1.0) < 1e-6, \
                f"Diagonal [{i}][{i}] should be 1.0, got {matrix[i][i]}"

    def test_symmetric(self):
        results = load_results()
        matrix = results['correlation_matrix']
        for i in range(5):
            for j in range(5):
                assert abs(matrix[i][j] - matrix[j][i]) < 1e-6, \
                    f"Matrix not symmetric at [{i}][{j}]"

    def test_in_range(self):
        results = load_results()
        matrix = results['correlation_matrix']
        for i in range(5):
            for j in range(5):
                assert -1 - 1e-6 <= matrix[i][j] <= 1 + 1e-6, \
                    f"Correlation out of range at [{i}][{j}]: {matrix[i][j]}"

    def test_correlation_values(self, ref_data):
        results = load_results()
        ref_corr = ref_data['correlation']
        matrix = results['correlation_matrix']
        for i in range(5):
            for j in range(i + 1, 5):
                assert abs(ref_corr[i][j] - matrix[i][j]) < 1e-3, \
                    f"Correlation mismatch at [{i}][{j}]: " \
                    f"expected {ref_corr[i][j]:.6f}, got {matrix[i][j]}"


# ============================================================
# Method evaluation tests
# ============================================================

class TestMethodEvaluation:
    def test_eigenvalues(self, ref_data):
        results = load_results()
        ref_evs = ref_data['method_eval']['eigenvalues']
        act_evs = results['method_evaluation']['eigenvalues']
        for i in range(5):
            assert abs(ref_evs[i] - act_evs[i]) < 0.01, \
                f"Eigenvalue [{i}] mismatch: " \
                f"expected {ref_evs[i]:.6f}, got {act_evs[i]}"

    def test_eigenvalues_sorted_descending(self):
        results = load_results()
        evs = results['method_evaluation']['eigenvalues']
        for i in range(len(evs) - 1):
            assert evs[i] >= evs[i + 1] - 1e-6, \
                f"Eigenvalues not sorted descending at index {i}"

    def test_eigenvalues_sum_to_five(self):
        """Eigenvalues of a 5x5 correlation matrix must sum to 5."""
        results = load_results()
        evs = results['method_evaluation']['eigenvalues']
        total = sum(evs)
        assert abs(total - 5.0) < 0.05, \
            f"Eigenvalues should sum to 5, got {total:.4f}"

    def test_effective_dimensions(self, ref_data):
        results = load_results()
        expected = ref_data['method_eval']['effective_dimensions']
        actual = results['method_evaluation']['effective_dimensions']
        assert actual == expected, \
            f"effective_dimensions should be {expected}, got {actual}"

    def test_effective_dimensions_range(self):
        results = load_results()
        ed = results['method_evaluation']['effective_dimensions']
        assert 1 <= ed <= 5, \
            f"effective_dimensions must be 1-5, got {ed}"

    def test_method_weights_sum_to_one(self):
        results = load_results()
        mw = results['method_evaluation']['method_weights']
        total = sum(mw.values())
        assert abs(total - 1.0) < 1e-4, \
            f"Method weights should sum to 1.0, got {total:.6f}"

    def test_method_weights_all_positive(self):
        results = load_results()
        mw = results['method_evaluation']['method_weights']
        for method, w in mw.items():
            assert w > 0, f"Weight for {method} should be positive, got {w}"

    def test_method_weights_values(self, ref_data):
        results = load_results()
        ref_weights = ref_data['method_eval']['weights']
        act_weights = results['method_evaluation']['method_weights']
        for method in ['brier', 'risk_neutral', 'kelly', 'crra_utility',
                       'pairwise_skill']:
            assert abs(ref_weights[method] - act_weights[method]) < 0.02, \
                f"Weight mismatch for {method}: " \
                f"expected {ref_weights[method]:.6f}, got {act_weights[method]}"

    def test_consensus_ranking_scores(self, ref_data):
        results = load_results()
        ref_consensus = ref_data['method_eval']['consensus_scores']
        cr = results['method_evaluation']['consensus_ranking']
        for entry in cr:
            fid = entry['forecaster_id']
            assert fid in ref_consensus, f"Unknown forecaster: {fid}"
            assert abs(ref_consensus[fid] - entry['score']) < 0.02, \
                f"Consensus score mismatch for {fid}: " \
                f"expected {ref_consensus[fid]:.6f}, got {entry['score']}"

    def test_consensus_ranking_top3(self, ref_data):
        ref_consensus = ref_data['method_eval']['consensus_scores']
        top3_exp = [x[0] for x in sorted(
            ref_consensus.items(), key=lambda x: -x[1])[:3]]
        results = load_results()
        top3_act = [e['forecaster_id']
                    for e in results['method_evaluation'][
                        'consensus_ranking'][:3]]
        assert top3_act == top3_exp, \
            f"Consensus top-3 mismatch: expected {top3_exp}, got {top3_act}"

    def test_consensus_all_forecasters(self):
        results = load_results()
        cr = results['method_evaluation']['consensus_ranking']
        expected_ids = {f"FC{i:03d}" for i in range(1, 26)}
        actual_ids = {e['forecaster_id'] for e in cr}
        assert actual_ids == expected_ids

    def test_consensus_scores_bounded(self):
        results = load_results()
        cr = results['method_evaluation']['consensus_ranking']
        for entry in cr:
            assert -0.01 <= entry['score'] <= 1.01, \
                f"Consensus score out of [0,1] for {entry['forecaster_id']}"

    def test_stability_spread_values(self, ref_data):
        results = load_results()
        ref_spread = ref_data['method_eval']['max_rank_spread']
        act_spread = results['method_evaluation'][
            'stability_analysis']['max_rank_spread']
        for fid in ref_spread:
            assert str(fid) in act_spread or fid in act_spread, \
                f"Missing spread for {fid}"
            act_val = act_spread.get(fid, act_spread.get(str(fid)))
            assert act_val == ref_spread[fid], \
                f"Rank spread mismatch for {fid}: " \
                f"expected {ref_spread[fid]}, got {act_val}"

    def test_most_stable_forecaster(self, ref_data):
        results = load_results()
        expected = ref_data['method_eval']['most_stable']
        actual = results['method_evaluation'][
            'stability_analysis']['most_stable_forecaster']
        assert actual == expected, \
            f"most_stable_forecaster should be {expected}, got {actual}"

    def test_least_stable_forecaster(self, ref_data):
        results = load_results()
        expected = ref_data['method_eval']['least_stable']
        actual = results['method_evaluation'][
            'stability_analysis']['least_stable_forecaster']
        assert actual == expected, \
            f"least_stable_forecaster should be {expected}, got {actual}"

    def test_stability_spread_nonnegative(self):
        results = load_results()
        spreads = results['method_evaluation'][
            'stability_analysis']['max_rank_spread']
        for fid, spread in spreads.items():
            assert spread >= 0, \
                f"Rank spread should be non-negative for {fid}"

    def test_stability_spread_bounded(self):
        results = load_results()
        spreads = results['method_evaluation'][
            'stability_analysis']['max_rank_spread']
        for fid, spread in spreads.items():
            assert spread <= 24, \
                f"Rank spread should be <= 24 for {fid}, got {spread}"


# ============================================================
# Anti-cheat: results must differ from buggy baseline
# ============================================================

class TestNotCopiedFromBaseline:
    def test_brier_differs(self):
        results = load_results()
        baseline = load_baseline()
        r_scores = {e['forecaster_id']: e['score']
                    for e in results['rankings']['brier']}
        b_scores = {e['forecaster_id']: e['score']
                    for e in baseline['brier']}
        diffs = [abs(r_scores[fid] - b_scores.get(fid, 0))
                 for fid in r_scores]
        assert max(diffs) > 0.001, \
            "Brier should differ from baseline (data cleaning needed)"

    def test_pairwise_differs(self):
        results = load_results()
        baseline = load_baseline()
        r_scores = {e['forecaster_id']: e['score']
                    for e in results['rankings']['pairwise_skill']}
        b_scores = {e['forecaster_id']: e['score']
                    for e in baseline['pairwise_skill']}
        diffs = [abs(r_scores[fid] - b_scores.get(fid, 0))
                 for fid in r_scores]
        assert max(diffs) > 0.01, \
            "Pairwise skill should differ from baseline (normalization needed)"
