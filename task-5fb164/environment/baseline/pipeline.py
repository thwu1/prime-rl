#!/usr/bin/env python3
"""Generate baseline results from SQLite database (contains known bugs)."""
import sqlite3
import json
import os
from collections import defaultdict


def main():
    db = sqlite3.connect('/app/data/forecasts.db')
    db.row_factory = sqlite3.Row

    # Load events
    events = {}
    for row in db.execute("SELECT event_id, category, outcome FROM events"):
        events[row['event_id']] = {
            'category': row['category'],
            'outcome': row['outcome']
        }

    # Load market data
    market = {}
    for row in db.execute("SELECT event_id, yes_price, no_price FROM markets"):
        market[row['event_id']] = {
            'yes_price': row['yes_price'],
            'no_price': row['no_price']
        }

    # Load forecasts
    forecasts = []
    for row in db.execute("SELECT event_id, forecaster_id, timestamp, probability FROM forecasts"):
        forecasts.append({
            'event_id': row['event_id'],
            'forecaster_id': row['forecaster_id'],
            'timestamp': row['timestamp'],
            'probability': row['probability']
        })

    db.close()

    # Deduplicate: keep EARLIEST timestamp per (event_id, forecaster_id)
    # (matches the buggy jq filter that uses .[0] after sort_by(.timestamp))
    best = {}
    for fc in forecasts:
        key = (fc['event_id'], fc['forecaster_id'])
        if key not in best or fc['timestamp'] < best[key]['timestamp']:
            best[key] = fc
    deduped = list(best.values())

    # Group by forecaster (does NOT filter unresolved or orphans)
    by_forecaster = defaultdict(list)
    for fc in deduped:
        eid = fc['event_id']
        if eid not in events:
            continue
        by_forecaster[fc['forecaster_id']].append(fc)

    # --- Brier scoring (uses max(0, outcome) for unresolved) ---
    brier = {}
    for fid, preds in by_forecaster.items():
        sq_errors = []
        for pred in preds:
            outcome = events[pred['event_id']]['outcome']
            actual = max(0, outcome)
            sq_errors.append((pred['probability'] - actual) ** 2)
        if sq_errors:
            brier[fid] = 1.0 - sum(sq_errors) / len(sq_errors)

    # --- Risk-neutral (buggy: prob * price instead of prob / price) ---
    risk_neutral = {}
    for fid, preds in by_forecaster.items():
        returns = []
        for pred in preds:
            eid = pred['event_id']
            if eid not in market:
                continue
            outcome = max(0, events[eid]['outcome'])
            prob = pred['probability']
            c_yes = market[eid]['yes_price']
            c_no = market[eid]['no_price']
            ev_yes = prob * c_yes - 1.0
            ev_no = (1.0 - prob) * c_no - 1.0
            if ev_yes > 0 and ev_yes >= ev_no:
                ret = (1.0 / c_yes - 1.0) if outcome == 1 else -1.0
            elif ev_no > 0:
                ret = (1.0 / c_no - 1.0) if outcome == 0 else -1.0
            else:
                ret = 0.0
            returns.append(ret)
        if returns:
            risk_neutral[fid] = sum(returns) / len(returns)

    # --- Kelly criterion ---
    kelly = {}
    for fid, preds in by_forecaster.items():
        returns = []
        for pred in preds:
            eid = pred['event_id']
            if eid not in market:
                continue
            outcome = max(0, events[eid]['outcome'])
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
            kelly[fid] = sum(returns) / len(returns)

    # --- CRRA utility (stub: returns 0 for all) ---
    crra_utility = {}
    for fid in by_forecaster:
        crra_utility[fid] = 0.0

    # --- Pairwise skill (no mean-normalization) ---
    preds_by_event = defaultdict(list)
    for fc in deduped:
        eid = fc['event_id']
        if eid in events:
            preds_by_event[eid].append(
                (fc['forecaster_id'], fc['probability']))

    forecaster_ids = sorted(by_forecaster.keys())
    n = len(forecaster_ids)
    fid_to_idx = {fid: i for i, fid in enumerate(forecaster_ids)}

    win_matrix = [[0.0] * n for _ in range(n)]
    for eid, epreds in preds_by_event.items():
        outcome = max(0, events[eid]['outcome'])
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

    total_comp = [[win_matrix[i][j] + win_matrix[j][i]
                   for j in range(n)] for i in range(n)]
    total_wins = [sum(win_matrix[i]) for i in range(n)]

    theta = [1.0] * n
    for _ in range(1000):
        theta_old = theta[:]
        for i in range(n):
            denom = 0.0
            for j in range(n):
                if i != j and total_comp[i][j] > 0:
                    denom += total_comp[i][j] / (theta_old[i] + theta_old[j])
            if denom > 0 and total_wins[i] > 0:
                theta[i] = total_wins[i] / denom
            else:
                theta[i] = theta_old[i]
        max_change = max(abs(theta[i] - theta_old[i]) for i in range(n))
        if max_change < 1e-8:
            break
    # NOTE: no normalization by mean

    pairwise_skill = {forecaster_ids[i]: theta[i] for i in range(n)}

    def sort_ranking(d):
        return [{"forecaster_id": k, "score": round(v, 6)}
                for k, v in sorted(d.items(), key=lambda x: -x[1])]

    results = {
        "brier": sort_ranking(brier),
        "risk_neutral": sort_ranking(risk_neutral),
        "kelly": sort_ranking(kelly),
        "crra_utility": sort_ranking(crra_utility),
        "pairwise_skill": sort_ranking(pairwise_skill)
    }

    os.makedirs('/app/baseline', exist_ok=True)
    with open('/app/baseline/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Baseline analysis complete.")


if __name__ == '__main__':
    main()
