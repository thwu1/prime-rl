#!/usr/bin/env python3

"""
Complete evaluation engine for the multi-task clinical challenge.
Reads input data, computes all metrics and rankings, writes leaderboard.json.
"""

import json
import os
import csv
import math
import numpy as np


# ── I/O ──────────────────────────────────────

def load_csv(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def get_teams():
    return sorted(os.listdir('/app/data/submissions'))


def load_submission(team):
    base = f'/app/data/submissions/{team}'
    out = {}
    for name in ('segmentation', 'survival', 'staging'):
        p = os.path.join(base, f'{name}.csv')
        if os.path.exists(p):
            out[name] = load_csv(p)
    return out


# ── Metrics ──────────────────────────────────

def gtvp_mean_dsc(seg):
    if seg is None:
        return 0.0
    vals = []
    for r in seg:
        vs = float(r['vol_sum_gtvp'])
        tp = float(r['tp_gtvp'])
        vals.append(2.0 * tp / vs if vs > 0 else 1.0)
    return float(np.mean(vals))


def gtvn_agg_dsc(seg):
    if seg is None:
        return 0.0
    t_tp = sum(float(r['tp_gtvn']) for r in seg)
    t_vs = sum(float(r['vol_sum_gtvn']) for r in seg)
    if t_vs == 0:
        return 1.0
    return 2.0 * t_tp / t_vs


def gtvn_agg_f1(seg, meta):
    if seg is None:
        total_fn = sum(int(r['n_gtvn_lesions']) for r in meta)
        return 1.0 if total_fn == 0 else 0.0
    t_tp = sum(int(r['tp_detect']) for r in seg)
    t_fp = sum(int(r['fp_detect']) for r in seg)
    t_fn = sum(int(r['fn_detect']) for r in seg)
    d = 2 * t_tp + t_fp + t_fn
    return 1.0 if d == 0 else 2.0 * t_tp / d


def concordance_index(event_times, pred_risks, event_obs):
    n = len(event_times)
    scores = []
    for r in pred_risks:
        if r is None or (isinstance(r, float) and math.isnan(r)):
            scores.append(float('nan'))
        else:
            scores.append(-float(r))

    nc, nt, npairs = 0.0, 0.0, 0.0
    for a in range(n):
        for b in range(a + 1, n):
            ta, tb = event_times[a], event_times[b]
            ea, eb = event_obs[a], event_obs[b]
            sa, sb = scores[a], scores[b]

            if ta == tb:
                if ea == eb:
                    continue
            elif ea and eb:
                pass
            elif ea and ta < tb:
                pass
            elif eb and tb < ta:
                pass
            else:
                continue

            npairs += 1
            if math.isnan(sa) or math.isnan(sb):
                nt += 1
                continue
            if sa == sb:
                nt += 1
                continue
            if sa < sb:
                if ta < tb or (ta == tb and ea and not eb):
                    nc += 1
            else:
                if ta > tb or (ta == tb and not ea and eb):
                    nc += 1

    return 0.5 if npairs == 0 else (nc + nt / 2.0) / npairs


def balanced_accuracy(true_labels, pred_labels, classes):
    recalls = []
    for c in classes:
        act = sum(1 for t in true_labels if t == c)
        if act == 0:
            continue
        cor = sum(1 for t, p in zip(true_labels, pred_labels)
                  if t == c and p == c)
        recalls.append(cor / act)
    return float(np.mean(recalls)) if recalls else 0.0


# ── Ranking ──────────────────────────────────

def rank_scores(team_scores, higher_is_better=True):
    items = sorted(team_scores.items(),
                   key=lambda x: x[1], reverse=higher_is_better)
    ranks = {}
    i = 0
    while i < len(items):
        j = i
        while j < len(items) and abs(items[j][1] - items[i][1]) < 1e-10:
            j += 1
        avg = sum(range(i + 1, j + 1)) / (j - i)
        for k in range(i, j):
            ranks[items[k][0]] = avg
        i = j
    return ranks


# ── Bootstrap ────────────────────────────────

def bootstrap_ci(teams, subs, stg_gt, srv_gt, seg_meta):
    rng = np.random.RandomState(12345)
    n = len(srv_gt)
    res = {t: dict(gtvp=[], gn_dsc=[], ci=[], ba=[]) for t in teams}

    for _ in range(1000):
        idx = rng.choice(n, size=n, replace=True)
        for team in teams:
            sub = subs[team]
            seg = sub.get('segmentation')
            if seg is None:
                res[team]['gtvp'].append(0.0)
                res[team]['gn_dsc'].append(0.0)
            else:
                ds, ttp, tvs = [], 0.0, 0.0
                for i in idx:
                    r = seg[i]
                    vs = float(r['vol_sum_gtvp'])
                    tp = float(r['tp_gtvp'])
                    ds.append(2.0 * tp / vs if vs > 0 else 1.0)
                    ttp += float(r['tp_gtvn'])
                    tvs += float(r['vol_sum_gtvn'])
                res[team]['gtvp'].append(float(np.mean(ds)))
                res[team]['gn_dsc'].append(
                    1.0 if tvs == 0 else 2.0 * ttp / tvs)

            surv = sub.get('survival', [])
            pm = {r['patient_id']: r['predicted_risk'] for r in surv}
            et = [float(srv_gt[i]['event_time']) for i in idx]
            eo = [int(srv_gt[i]['event_observed']) for i in idx]
            pr = []
            for i in idx:
                v = pm.get(srv_gt[i]['patient_id'], '')
                pr.append(float('nan') if v == '' else float(v))
            res[team]['ci'].append(concordance_index(et, pr, eo))

            stg = sub.get('staging', [])
            sm = {r['patient_id']: r for r in stg}
            tt = [stg_gt[i]['t_stage'] for i in idx]
            tn = [stg_gt[i]['n_stage'] for i in idx]
            pt = [sm[stg_gt[i]['patient_id']]['predicted_t'] for i in idx]
            pn = [sm[stg_gt[i]['patient_id']]['predicted_n'] for i in idx]
            tba = balanced_accuracy(tt, pt, ['T1', 'T2', 'T3', 'T4'])
            nba = balanced_accuracy(tn, pn, ['N0', 'N1', 'N2', 'N3'])
            res[team]['ba'].append((tba + nba) / 2.0)

    cis = {}
    for t in teams:
        cis[t] = {
            'gtvp_mean_dsc': [
                round(float(np.percentile(res[t]['gtvp'], 2.5)), 6),
                round(float(np.percentile(res[t]['gtvp'], 97.5)), 6)],
            'gtvn_agg_dsc': [
                round(float(np.percentile(res[t]['gn_dsc'], 2.5)), 6),
                round(float(np.percentile(res[t]['gn_dsc'], 97.5)), 6)],
            'c_index': [
                round(float(np.percentile(res[t]['ci'], 2.5)), 6),
                round(float(np.percentile(res[t]['ci'], 97.5)), 6)],
            'mean_balanced_accuracy': [
                round(float(np.percentile(res[t]['ba'], 2.5)), 6),
                round(float(np.percentile(res[t]['ba'], 97.5)), 6)],
        }
    return cis


# ── Main ─────────────────────────────────────

def main():
    teams = get_teams()
    stg_gt = load_csv('/app/data/ground_truth/staging.csv')
    srv_gt = load_csv('/app/data/ground_truth/survival.csv')
    seg_meta = load_csv('/app/data/ground_truth/segmentation_meta.csv')
    subs = {t: load_submission(t) for t in teams}

    # ── per-team metrics ──
    raw = {}
    for team in teams:
        sub = subs[team]
        seg = sub.get('segmentation')

        gp = gtvp_mean_dsc(seg)
        gn_d = gtvn_agg_dsc(seg)
        gn_f = gtvn_agg_f1(seg, seg_meta)

        surv = sub.get('survival', [])
        pm = {r['patient_id']: r['predicted_risk'] for r in surv}
        et = [float(r['event_time']) for r in srv_gt]
        eo = [int(r['event_observed']) for r in srv_gt]
        pr = []
        for r in srv_gt:
            v = pm.get(r['patient_id'], '')
            pr.append(float('nan') if v == '' else float(v))
        ci = concordance_index(et, pr, eo)

        stg = sub.get('staging', [])
        sm = {r['patient_id']: r for r in stg}
        tt = [r['t_stage'] for r in stg_gt]
        tn = [r['n_stage'] for r in stg_gt]
        pt = [sm[r['patient_id']]['predicted_t'] for r in stg_gt]
        pn = [sm[r['patient_id']]['predicted_n'] for r in stg_gt]
        t_ba = balanced_accuracy(tt, pt, ['T1', 'T2', 'T3', 'T4'])
        n_ba = balanced_accuracy(tn, pn, ['N0', 'N1', 'N2', 'N3'])

        raw[team] = dict(
            gtvp_mean_dsc=gp, gtvn_agg_dsc=gn_d, gtvn_agg_f1=gn_f,
            c_index=ci, t_balanced_accuracy=t_ba,
            n_balanced_accuracy=n_ba,
            mean_balanced_accuracy=(t_ba + n_ba) / 2.0)

    team_metrics = {
        t: {k: round(v, 6) for k, v in raw[t].items()} for t in teams}

    # ── rankings ──
    gtvp_r = rank_scores(
        {t: raw[t]['gtvp_mean_dsc'] for t in teams}, True)
    gn_s_r = rank_scores(
        {t: raw[t]['gtvn_agg_dsc'] for t in teams}, True)
    gn_d_r = rank_scores(
        {t: raw[t]['gtvn_agg_f1'] for t in teams}, True)

    gn_borda = {t: gn_s_r[t] + gn_d_r[t] for t in teams}
    gn_b_r = rank_scores(gn_borda, False)

    seg_borda = {t: gtvp_r[t] + gn_b_r[t] for t in teams}
    seg_r = rank_scores(seg_borda, False)

    prog_r = rank_scores({t: raw[t]['c_index'] for t in teams}, True)
    stg_r = rank_scores(
        {t: raw[t]['mean_balanced_accuracy'] for t in teams}, True)

    ws, cs = {}, {}
    for t in teams:
        w = 0.25 * seg_r[t] + 0.35 * stg_r[t] + 0.40 * prog_r[t]
        u = (seg_r[t] + stg_r[t] + prog_r[t]) / 3.0
        ws[t] = w
        cs[t] = abs(w - u)

    order = sorted(teams, key=lambda t: (ws[t], cs[t]))
    final_rank = {order[i]: i + 1 for i in range(len(order))}

    rankings = {}
    for t in teams:
        rankings[t] = dict(
            gtvp_rank=round(gtvp_r[t], 6),
            gtvn_seg_rank=round(gn_s_r[t], 6),
            gtvn_det_rank=round(gn_d_r[t], 6),
            gtvn_borda=round(gn_borda[t], 6),
            gtvn_borda_rank=round(gn_b_r[t], 6),
            seg_borda=round(seg_borda[t], 6),
            seg_rank=round(seg_r[t], 6),
            prog_rank=round(prog_r[t], 6),
            stage_rank=round(stg_r[t], 6),
            weighted_score=round(ws[t], 6),
            consistency=round(cs[t], 6),
            final_rank=final_rank[t])

    # ── bootstrap ──
    bci = bootstrap_ci(teams, subs, stg_gt, srv_gt, seg_meta)

    # ── output ──
    result = dict(
        team_metrics=team_metrics,
        rankings=rankings,
        final_ranking=order,
        bootstrap_ci=bci)

    os.makedirs('/app/output', exist_ok=True)
    with open('/app/output/leaderboard.json', 'w') as f:
        json.dump(result, f, indent=2)

    print("Leaderboard written to /app/output/leaderboard.json")
    print(f"Final ranking: {order}")


if __name__ == '__main__':
    main()
