#!/usr/bin/env python3
"""Evaluation pipeline for the multi-task clinical challenge.
Reads data from the SQLite database and produces leaderboard rankings."""

import json
import os
import math
import sqlite3
import numpy as np

try:
    import tomllib
except ImportError:
    import tomli as tomllib


def load_config(path='/app/evaluator/config.toml'):
    with open(path, 'rb') as f:
        return tomllib.load(f)


def get_db(path='/app/data/challenge.db'):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def query_teams(conn):
    rows = conn.execute(
        "SELECT DISTINCT team FROM submissions_staging ORDER BY team"
    ).fetchall()
    return [r['team'] for r in rows]


def query_ground_truth(conn):
    stg = [dict(r) for r in conn.execute(
        "SELECT * FROM ground_truth_staging ORDER BY patient_id"
    ).fetchall()]
    srv = [dict(r) for r in conn.execute(
        "SELECT * FROM ground_truth_survival ORDER BY patient_id"
    ).fetchall()]
    meta = [dict(r) for r in conn.execute(
        "SELECT * FROM segmentation_meta ORDER BY patient_id"
    ).fetchall()]
    return stg, srv, meta


def query_submission(conn, team):
    sub = {}
    seg_rows = conn.execute(
        "SELECT patient_id, tp_gtvp, vol_sum_gtvp, tp_gtvn, vol_sum_gtvn, "
        "tp_detect, fp_detect, fn_detect "
        "FROM submissions_segmentation WHERE team = ? ORDER BY patient_id",
        (team,)
    ).fetchall()
    if seg_rows:
        sub['segmentation'] = [dict(r) for r in seg_rows]

    srv_rows = conn.execute(
        "SELECT patient_id, predicted_risk "
        "FROM submissions_survival WHERE team = ? ORDER BY patient_id",
        (team,)
    ).fetchall()
    sub['survival'] = [dict(r) for r in srv_rows]

    stg_rows = conn.execute(
        "SELECT patient_id, predicted_t, predicted_n "
        "FROM submissions_staging WHERE team = ? ORDER BY patient_id",
        (team,)
    ).fetchall()
    sub['staging'] = [dict(r) for r in stg_rows]

    return sub


# ── Metrics ────────────────────────────────────────────

def compute_gtvp_mean_dsc(seg):
    """Mean per-patient Dice for primary tumor."""
    if seg is None:
        return 0.0
    vals = []
    for r in seg:
        vs = float(r['vol_sum_gtvp'])
        tp = float(r['tp_gtvp'])
        vals.append(2.0 * tp / vs if vs > 0 else 1.0)
    return float(np.mean(vals))


def compute_gtvn_dsc(seg):
    """Dice coefficient for lymph-node tumors."""
    if seg is None:
        return 0.0
    vals = []
    for r in seg:
        vs = float(r['vol_sum_gtvn'])
        tp = float(r['tp_gtvn'])
        vals.append(2.0 * tp / vs if vs > 0 else 1.0)
    return float(np.mean(vals))


def compute_gtvn_f1(seg, meta):
    """Detection F1-score for lymph-node lesions."""
    if seg is None:
        return 1.0
    t_tp = sum(int(r['tp_detect']) for r in seg)
    t_fp = sum(int(r['fp_detect']) for r in seg)
    t_fn = sum(int(r['fn_detect']) for r in seg)
    d = 2 * t_tp + t_fp + t_fn
    return 1.0 if d == 0 else 2.0 * t_tp / d


def compute_cindex(event_times, pred_risks, event_obs):
    """Concordance index for survival predictions."""
    n = len(event_times)
    scores = []
    for r in pred_risks:
        if r is None or r == '' or (isinstance(r, float) and math.isnan(r)):
            scores.append(float('nan'))
        else:
            scores.append(float(r))

    nc, nt, np_ = 0.0, 0.0, 0.0
    for a in range(n):
        for b in range(a + 1, n):
            ta, tb = event_times[a], event_times[b]
            ea, eb = event_obs[a], event_obs[b]
            sa, sb = scores[a], scores[b]

            if ta == tb:
                continue
            elif ea and eb:
                pass
            elif ea and ta < tb:
                pass
            elif eb and tb < ta:
                pass
            else:
                continue

            np_ += 1
            if math.isnan(sa) or math.isnan(sb):
                nt += 1
                continue
            if sa == sb:
                nt += 1
                continue
            if sa < sb:
                if ta < tb:
                    nc += 1
            elif sa > sb:
                if ta > tb:
                    nc += 1

    return 0.5 if np_ == 0 else (nc + nt / 2.0) / np_


def compute_balanced_accuracy(true_labels, pred_labels, classes):
    """Balanced accuracy as mean per-class recall."""
    recalls = []
    for c in classes:
        act = sum(1 for t in true_labels if t == c)
        if act == 0:
            continue
        cor = sum(1 for t, p in zip(true_labels, pred_labels)
                  if t == c and p == c)
        recalls.append(cor / act)
    return float(np.mean(recalls)) if recalls else 0.0


# ── Ranking ────────────────────────────────────────────

def rank_teams(team_scores, higher_is_better=True):
    """Rank teams by score."""
    items = sorted(team_scores.items(),
                   key=lambda x: x[1], reverse=higher_is_better)
    ranks = {}
    for i, (team, _) in enumerate(items):
        ranks[team] = float(i + 1)
    return ranks


# ── Bootstrap ──────────────────────────────────────────

def run_bootstrap(config, teams, subs, stg_gt, srv_gt, seg_meta):
    seed = config['bootstrap']['seed']
    n_iter = config['bootstrap']['n_iterations']
    rng = np.random.RandomState(seed)
    n = len(srv_gt)
    res = {t: dict(gtvp=[], gn_dsc=[], ci=[], ba=[]) for t in teams}

    for _ in range(n_iter):
        idx = rng.choice(n, size=n, replace=True)
        for team in teams:
            sub = subs[team]
            seg = sub.get('segmentation')
            if seg is None:
                res[team]['gtvp'].append(0.0)
                res[team]['gn_dsc'].append(0.0)
            else:
                ds_p, ds_n = [], []
                for i in idx:
                    r = seg[i]
                    vs_p = float(r['vol_sum_gtvp'])
                    tp_p = float(r['tp_gtvp'])
                    ds_p.append(2.0 * tp_p / vs_p if vs_p > 0 else 1.0)
                    vs_n = float(r['vol_sum_gtvn'])
                    tp_n = float(r['tp_gtvn'])
                    ds_n.append(2.0 * tp_n / vs_n if vs_n > 0 else 1.0)
                res[team]['gtvp'].append(float(np.mean(ds_p)))
                res[team]['gn_dsc'].append(float(np.mean(ds_n)))

            surv = sub.get('survival', [])
            pm = {r['patient_id']: r.get('predicted_risk', '') for r in surv}
            et = [float(srv_gt[i]['event_time']) for i in idx]
            eo = [int(srv_gt[i]['event_observed']) for i in idx]
            pr = []
            for i in idx:
                v = pm.get(srv_gt[i]['patient_id'], '')
                if v is None or v == '':
                    pr.append(float('nan'))
                else:
                    pr.append(float(v))
            res[team]['ci'].append(compute_cindex(et, pr, eo))

            stg = sub.get('staging', [])
            sm = {r['patient_id']: r for r in stg}
            tt = [stg_gt[i]['t_stage'] for i in idx]
            tn = [stg_gt[i]['n_stage'] for i in idx]
            pt = [sm[stg_gt[i]['patient_id']]['predicted_t'] for i in idx]
            pn = [sm[stg_gt[i]['patient_id']]['predicted_n'] for i in idx]
            tba = compute_balanced_accuracy(tt, pt, ['T1', 'T2', 'T3', 'T4'])
            nba = compute_balanced_accuracy(tn, pn, ['N0', 'N1', 'N2', 'N3'])
            res[team]['ba'].append((tba + nba) / 2.0)

    precision = config['output']['precision']
    cis = {}
    for t in teams:
        cis[t] = {
            'gtvp_mean_dsc': [
                round(float(np.percentile(res[t]['gtvp'], 2.5)), precision),
                round(float(np.percentile(res[t]['gtvp'], 97.5)), precision)],
            'gtvn_agg_dsc': [
                round(float(np.percentile(res[t]['gn_dsc'], 2.5)), precision),
                round(float(np.percentile(res[t]['gn_dsc'], 97.5)), precision)],
            'c_index': [
                round(float(np.percentile(res[t]['ci'], 2.5)), precision),
                round(float(np.percentile(res[t]['ci'], 97.5)), precision)],
            'mean_balanced_accuracy': [
                round(float(np.percentile(res[t]['ba'], 2.5)), precision),
                round(float(np.percentile(res[t]['ba'], 97.5)), precision)],
        }
    return cis


# ── Main ───────────────────────────────────────────────

def main():
    config = load_config()
    conn = get_db()

    teams = query_teams(conn)
    stg_gt, srv_gt, seg_meta = query_ground_truth(conn)
    subs = {t: query_submission(conn, t) for t in teams}

    conn.close()

    precision = config['output']['precision']

    # ── per-team metrics ──
    raw = {}
    for team in teams:
        sub = subs[team]
        seg = sub.get('segmentation')

        gp = compute_gtvp_mean_dsc(seg)
        gn_d = compute_gtvn_dsc(seg)
        gn_f = compute_gtvn_f1(seg, seg_meta)

        surv = sub.get('survival', [])
        pm = {r['patient_id']: r.get('predicted_risk', '') for r in surv}
        et = [float(r['event_time']) for r in srv_gt]
        eo = [int(r['event_observed']) for r in srv_gt]
        pr = []
        for r in srv_gt:
            v = pm.get(r['patient_id'], '')
            if v is None or v == '':
                pr.append(float('nan'))
            else:
                pr.append(float(v))
        ci = compute_cindex(et, pr, eo)

        stg = sub.get('staging', [])
        sm = {r['patient_id']: r for r in stg}
        tt = [r['t_stage'] for r in stg_gt]
        tn = [r['n_stage'] for r in stg_gt]
        pt = [sm[r['patient_id']]['predicted_t'] for r in stg_gt]
        pn = [sm[r['patient_id']]['predicted_n'] for r in stg_gt]
        t_ba = compute_balanced_accuracy(tt, pt, ['T1', 'T2', 'T3', 'T4'])
        n_ba = compute_balanced_accuracy(tn, pn, ['N0', 'N1', 'N2', 'N3'])

        raw[team] = dict(
            gtvp_mean_dsc=gp, gtvn_agg_dsc=gn_d, gtvn_agg_f1=gn_f,
            c_index=ci, t_balanced_accuracy=t_ba,
            n_balanced_accuracy=n_ba,
            mean_balanced_accuracy=(t_ba + n_ba) / 2.0)

    team_metrics = {
        t: {k: round(v, precision) for k, v in raw[t].items()}
        for t in teams}

    # ── rankings ──
    gtvp_r = rank_teams(
        {t: raw[t]['gtvp_mean_dsc'] for t in teams}, True)
    gn_s_r = rank_teams(
        {t: raw[t]['gtvn_agg_dsc'] for t in teams}, True)
    gn_d_r = rank_teams(
        {t: raw[t]['gtvn_agg_f1'] for t in teams}, True)

    gn_borda = {t: gn_s_r[t] + gn_d_r[t] for t in teams}
    gn_b_r = rank_teams(gn_borda, False)

    seg_borda = {t: gtvp_r[t] + gn_b_r[t] for t in teams}
    seg_r = rank_teams(seg_borda, False)

    prog_r = rank_teams({t: raw[t]['c_index'] for t in teams}, True)
    stg_r = rank_teams(
        {t: raw[t]['mean_balanced_accuracy'] for t in teams}, True)

    ws, cs = {}, {}
    for t in teams:
        w = (config['weights']['segmentation'] * seg_r[t] +
             config['weights']['staging'] * stg_r[t] +
             config['weights']['prognosis'] * prog_r[t])
        u = (seg_r[t] + stg_r[t] + prog_r[t]) / 3.0
        ws[t] = w
        cs[t] = abs(w - u)

    order = sorted(teams, key=lambda t: (ws[t], cs[t]))
    final_rank = {order[i]: i + 1 for i in range(len(order))}

    rankings = {}
    for t in teams:
        rankings[t] = dict(
            gtvp_rank=round(gtvp_r[t], precision),
            gtvn_seg_rank=round(gn_s_r[t], precision),
            gtvn_det_rank=round(gn_d_r[t], precision),
            gtvn_borda=round(gn_borda[t], precision),
            gtvn_borda_rank=round(gn_b_r[t], precision),
            seg_borda=round(seg_borda[t], precision),
            seg_rank=round(seg_r[t], precision),
            prog_rank=round(prog_r[t], precision),
            stage_rank=round(stg_r[t], precision),
            weighted_score=round(ws[t], precision),
            consistency=round(cs[t], precision),
            final_rank=final_rank[t])

    # ── bootstrap ──
    bci = run_bootstrap(config, teams, subs, stg_gt, srv_gt, seg_meta)

    # ── output ──
    result = dict(
        team_metrics=team_metrics,
        rankings=rankings,
        final_ranking=order,
        bootstrap_ci=bci)

    os.makedirs(os.path.dirname(config['output']['path']), exist_ok=True)
    with open(config['output']['path'], 'w') as f:
        json.dump(result, f, indent=2)

    print(f"Leaderboard written to {config['output']['path']}")
    print(f"Final ranking: {order}")


if __name__ == '__main__':
    main()
