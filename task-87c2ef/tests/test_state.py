
"""
Reference-implementation tests for the multi-task clinical challenge
evaluation engine.  Every expected value is computed independently from
the raw input data — no hardcoded answers.
"""

import json
import os
import csv
import math
import numpy as np
import pytest

TOLERANCE = 1e-4
CI_TOLERANCE = 0.02


# ──────────────────────────────────────────────
#  Data-loading helpers
# ──────────────────────────────────────────────

def _load_csv(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def _load_json(path):
    with open(path) as f:
        return json.load(f)


def _get_teams():
    return sorted(os.listdir('/app/data/submissions'))


def _load_submission(team):
    base = f'/app/data/submissions/{team}'
    out = {}
    for name in ('segmentation', 'survival', 'staging'):
        p = os.path.join(base, f'{name}.csv')
        if os.path.exists(p):
            out[name] = _load_csv(p)
    return out


# ──────────────────────────────────────────────
#  Reference metric implementations
# ──────────────────────────────────────────────

def _ref_gtvp_mean_dsc(seg):
    if seg is None:
        return 0.0
    vals = []
    for r in seg:
        vs = float(r['vol_sum_gtvp'])
        tp = float(r['tp_gtvp'])
        vals.append(2.0 * tp / vs if vs > 0 else 1.0)
    return float(np.mean(vals))


def _ref_gtvn_agg_dsc(seg):
    if seg is None:
        return 0.0
    t_tp = sum(float(r['tp_gtvn']) for r in seg)
    t_vs = sum(float(r['vol_sum_gtvn']) for r in seg)
    if t_vs == 0:
        return 1.0
    return 2.0 * t_tp / t_vs


def _ref_gtvn_mean_dsc(seg):
    """Mean of per-patient DSC — the WRONG metric.  Used to verify the
    agent did not confuse it with the aggregated variant."""
    if seg is None:
        return 0.0
    vals = []
    for r in seg:
        vs = float(r['vol_sum_gtvn'])
        tp = float(r['tp_gtvn'])
        vals.append(2.0 * tp / vs if vs > 0 else 1.0)
    return float(np.mean(vals))


def _ref_gtvn_agg_f1(seg, meta):
    if seg is None:
        total_fn = sum(int(r['n_gtvn_lesions']) for r in meta)
        return 1.0 if total_fn == 0 else 0.0
    t_tp = sum(int(r['tp_detect']) for r in seg)
    t_fp = sum(int(r['fp_detect']) for r in seg)
    t_fn = sum(int(r['fn_detect']) for r in seg)
    d = 2 * t_tp + t_fp + t_fn
    return 1.0 if d == 0 else 2.0 * t_tp / d


def _ref_cindex(event_times, pred_risks, event_obs):
    """C-index with negated risk scores; NaN treated as tied."""
    n = len(event_times)
    scores = []
    for r in pred_risks:
        if r is None or (isinstance(r, float) and math.isnan(r)):
            scores.append(float('nan'))
        else:
            scores.append(-float(r))

    nc, nt, np_ = 0.0, 0.0, 0.0
    for a in range(n):
        for b in range(a + 1, n):
            ta, tb = event_times[a], event_times[b]
            ea, eb = event_obs[a], event_obs[b]
            sa, sb = scores[a], scores[b]

            # admissibility
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

            np_ += 1

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

    return 0.5 if np_ == 0 else (nc + nt / 2.0) / np_


def _ref_balanced_accuracy(true_labels, pred_labels, classes):
    recalls = []
    for c in classes:
        act = sum(1 for t in true_labels if t == c)
        if act == 0:
            continue
        cor = sum(1 for t, p in zip(true_labels, pred_labels)
                  if t == c and p == c)
        recalls.append(cor / act)
    return float(np.mean(recalls)) if recalls else 0.0


def _ref_rank(team_scores, higher_is_better=True):
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


# ──────────────────────────────────────────────
#  Compute all expected values from raw data
# ──────────────────────────────────────────────

def _compute_expected():
    teams = _get_teams()
    stg_gt = _load_csv('/app/data/ground_truth/staging.csv')
    srv_gt = _load_csv('/app/data/ground_truth/survival.csv')
    seg_meta = _load_csv('/app/data/ground_truth/segmentation_meta.csv')
    subs = {t: _load_submission(t) for t in teams}

    metrics = {}
    for team in teams:
        sub = subs[team]
        seg = sub.get('segmentation')

        gp = _ref_gtvp_mean_dsc(seg)
        gn_dsc = _ref_gtvn_agg_dsc(seg)
        gn_f1 = _ref_gtvn_agg_f1(seg, seg_meta)

        surv = sub.get('survival', [])
        pm = {r['patient_id']: r['predicted_risk'] for r in surv}
        et = [float(r['event_time']) for r in srv_gt]
        eo = [int(r['event_observed']) for r in srv_gt]
        pr = []
        for r in srv_gt:
            v = pm.get(r['patient_id'], '')
            pr.append(float('nan') if v == '' else float(v))
        ci = _ref_cindex(et, pr, eo)

        stg = sub.get('staging', [])
        sm = {r['patient_id']: r for r in stg}
        tt = [r['t_stage'] for r in stg_gt]
        tn = [r['n_stage'] for r in stg_gt]
        pt = [sm[r['patient_id']]['predicted_t'] for r in stg_gt]
        pn = [sm[r['patient_id']]['predicted_n'] for r in stg_gt]
        t_ba = _ref_balanced_accuracy(tt, pt, ['T1', 'T2', 'T3', 'T4'])
        n_ba = _ref_balanced_accuracy(tn, pn, ['N0', 'N1', 'N2', 'N3'])

        metrics[team] = dict(
            gtvp_mean_dsc=gp, gtvn_agg_dsc=gn_dsc, gtvn_agg_f1=gn_f1,
            c_index=ci, t_balanced_accuracy=t_ba,
            n_balanced_accuracy=n_ba,
            mean_balanced_accuracy=(t_ba + n_ba) / 2.0,
        )

    # rankings
    gtvp_r = _ref_rank({t: metrics[t]['gtvp_mean_dsc'] for t in teams}, True)
    gn_s_r = _ref_rank({t: metrics[t]['gtvn_agg_dsc'] for t in teams}, True)
    gn_d_r = _ref_rank({t: metrics[t]['gtvn_agg_f1'] for t in teams}, True)

    gn_borda = {t: gn_s_r[t] + gn_d_r[t] for t in teams}
    gn_b_r = _ref_rank(gn_borda, False)

    seg_borda = {t: gtvp_r[t] + gn_b_r[t] for t in teams}
    seg_r = _ref_rank(seg_borda, False)

    prog_r = _ref_rank({t: metrics[t]['c_index'] for t in teams}, True)
    stg_r = _ref_rank(
        {t: metrics[t]['mean_balanced_accuracy'] for t in teams}, True)

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
            gtvp_rank=gtvp_r[t], gtvn_seg_rank=gn_s_r[t],
            gtvn_det_rank=gn_d_r[t], gtvn_borda=gn_borda[t],
            gtvn_borda_rank=gn_b_r[t], seg_borda=seg_borda[t],
            seg_rank=seg_r[t], prog_rank=prog_r[t],
            stage_rank=stg_r[t], weighted_score=ws[t],
            consistency=cs[t], final_rank=final_rank[t],
        )

    return metrics, rankings, order, subs, seg_meta, stg_gt, srv_gt


def _compute_bootstrap(teams, subs, stg_gt, srv_gt, seg_meta):
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
                ds, ttp_n, tvs_n = [], 0.0, 0.0
                for i in idx:
                    r = seg[i]
                    vs = float(r['vol_sum_gtvp'])
                    tp = float(r['tp_gtvp'])
                    ds.append(2.0 * tp / vs if vs > 0 else 1.0)
                    ttp_n += float(r['tp_gtvn'])
                    tvs_n += float(r['vol_sum_gtvn'])
                res[team]['gtvp'].append(float(np.mean(ds)))
                res[team]['gn_dsc'].append(
                    1.0 if tvs_n == 0 else 2.0 * ttp_n / tvs_n)

            surv = sub.get('survival', [])
            pm = {r['patient_id']: r['predicted_risk'] for r in surv}
            et = [float(srv_gt[i]['event_time']) for i in idx]
            eo = [int(srv_gt[i]['event_observed']) for i in idx]
            pr = []
            for i in idx:
                v = pm.get(srv_gt[i]['patient_id'], '')
                pr.append(float('nan') if v == '' else float(v))
            res[team]['ci'].append(_ref_cindex(et, pr, eo))

            stg = sub.get('staging', [])
            sm = {r['patient_id']: r for r in stg}
            tt = [stg_gt[i]['t_stage'] for i in idx]
            tn = [stg_gt[i]['n_stage'] for i in idx]
            pt = [sm[stg_gt[i]['patient_id']]['predicted_t'] for i in idx]
            pn = [sm[stg_gt[i]['patient_id']]['predicted_n'] for i in idx]
            tba = _ref_balanced_accuracy(tt, pt, ['T1', 'T2', 'T3', 'T4'])
            nba = _ref_balanced_accuracy(tn, pn, ['N0', 'N1', 'N2', 'N3'])
            res[team]['ba'].append((tba + nba) / 2.0)

    cis = {}
    for t in teams:
        cis[t] = {
            'gtvp_mean_dsc': [float(np.percentile(res[t]['gtvp'], 2.5)),
                              float(np.percentile(res[t]['gtvp'], 97.5))],
            'gtvn_agg_dsc': [float(np.percentile(res[t]['gn_dsc'], 2.5)),
                             float(np.percentile(res[t]['gn_dsc'], 97.5))],
            'c_index': [float(np.percentile(res[t]['ci'], 2.5)),
                        float(np.percentile(res[t]['ci'], 97.5))],
            'mean_balanced_accuracy': [
                float(np.percentile(res[t]['ba'], 2.5)),
                float(np.percentile(res[t]['ba'], 97.5))],
        }
    return cis


# ──────────────────────────────────────────────
#  Fixtures
# ──────────────────────────────────────────────

@pytest.fixture(scope='module')
def output():
    return _load_json('/app/output/leaderboard.json')


@pytest.fixture(scope='module')
def expected():
    return _compute_expected()


@pytest.fixture(scope='module')
def expected_ci(expected):
    _, _, _, subs, seg_meta, stg_gt, srv_gt = expected
    teams = _get_teams()
    return _compute_bootstrap(teams, subs, stg_gt, srv_gt, seg_meta)


# ──────────────────────────────────────────────
#  Tests
# ──────────────────────────────────────────────

class TestOutputStructure:
    def test_file_exists(self):
        assert os.path.exists('/app/output/leaderboard.json'), \
            "leaderboard.json not found"

    def test_valid_json(self, output):
        assert isinstance(output, dict)

    def test_required_keys(self, output):
        for key in ('team_metrics', 'rankings', 'final_ranking',
                     'bootstrap_ci'):
            assert key in output, f"Missing top-level key: {key}"

    def test_all_teams_present(self, output):
        for t in _get_teams():
            assert t in output['team_metrics'], f"Missing team {t}"
            assert t in output['rankings'], f"Missing ranking for {t}"
            assert t in output['bootstrap_ci'], f"Missing CI for {t}"


class TestGTVpMeanDSC:
    def test_values(self, output, expected):
        metrics = expected[0]
        for team, m in metrics.items():
            actual = output['team_metrics'][team]['gtvp_mean_dsc']
            assert abs(actual - m['gtvp_mean_dsc']) < TOLERANCE, \
                f"{team}: got {actual}, expected {m['gtvp_mean_dsc']}"


class TestGTVnAggDSC:
    def test_values(self, output, expected):
        metrics = expected[0]
        for team, m in metrics.items():
            actual = output['team_metrics'][team]['gtvn_agg_dsc']
            assert abs(actual - m['gtvn_agg_dsc']) < TOLERANCE, \
                f"{team}: got {actual}, expected {m['gtvn_agg_dsc']}"

    def test_not_mean_dsc(self, output):
        """Verify the agent used aggregated DSC, not mean per-patient DSC."""
        for team in _get_teams():
            sub = _load_submission(team)
            seg = sub.get('segmentation')
            if seg is None:
                continue
            agg = _ref_gtvn_agg_dsc(seg)
            mean = _ref_gtvn_mean_dsc(seg)
            actual = output['team_metrics'][team]['gtvn_agg_dsc']
            # If agg and mean differ significantly, the output must match agg
            if abs(agg - mean) > 0.005:
                assert abs(actual - agg) < TOLERANCE, (
                    f"{team}: output ({actual:.6f}) looks like mean DSC "
                    f"({mean:.6f}) instead of aggregated ({agg:.6f})")


class TestGTVnAggF1:
    def test_values(self, output, expected):
        metrics = expected[0]
        for team, m in metrics.items():
            actual = output['team_metrics'][team]['gtvn_agg_f1']
            assert abs(actual - m['gtvn_agg_f1']) < TOLERANCE, \
                f"{team}: got {actual}, expected {m['gtvn_agg_f1']}"


class TestMissingSegmentation:
    """team_e has no segmentation submission."""
    def test_gtvp_zero(self, output):
        assert abs(output['team_metrics']['team_e']['gtvp_mean_dsc']) \
            < TOLERANCE

    def test_gtvn_dsc_zero(self, output):
        assert abs(output['team_metrics']['team_e']['gtvn_agg_dsc']) \
            < TOLERANCE

    def test_gtvn_f1_zero(self, output):
        assert abs(output['team_metrics']['team_e']['gtvn_agg_f1']) \
            < TOLERANCE


class TestCIndex:
    def test_values(self, output, expected):
        metrics = expected[0]
        for team, m in metrics.items():
            actual = output['team_metrics'][team]['c_index']
            assert abs(actual - m['c_index']) < TOLERANCE, \
                f"{team}: got {actual}, expected {m['c_index']}"

    def test_nan_handling(self, output, expected):
        """team_f has missing predictions — C-index should still be valid."""
        ci = output['team_metrics']['team_f']['c_index']
        assert 0.0 <= ci <= 1.0, f"team_f C-index out of range: {ci}"
        expected_ci = expected[0]['team_f']['c_index']
        assert abs(ci - expected_ci) < TOLERANCE


class TestBalancedAccuracy:
    def test_t_ba(self, output, expected):
        metrics = expected[0]
        for team, m in metrics.items():
            actual = output['team_metrics'][team]['t_balanced_accuracy']
            assert abs(actual - m['t_balanced_accuracy']) < TOLERANCE, \
                f"{team}: T-BA {actual} != {m['t_balanced_accuracy']}"

    def test_n_ba(self, output, expected):
        metrics = expected[0]
        for team, m in metrics.items():
            actual = output['team_metrics'][team]['n_balanced_accuracy']
            assert abs(actual - m['n_balanced_accuracy']) < TOLERANCE, \
                f"{team}: N-BA {actual} != {m['n_balanced_accuracy']}"

    def test_mean_ba(self, output, expected):
        metrics = expected[0]
        for team, m in metrics.items():
            actual = output['team_metrics'][team]['mean_balanced_accuracy']
            assert abs(actual - m['mean_balanced_accuracy']) < TOLERANCE, \
                f"{team}: mean-BA {actual} != {m['mean_balanced_accuracy']}"


class TestSegmentationRanking:
    def test_seg_rank(self, output, expected):
        rankings = expected[1]
        for team, r in rankings.items():
            actual = output['rankings'][team]['seg_rank']
            assert abs(actual - r['seg_rank']) < TOLERANCE, \
                f"{team}: seg_rank {actual} != {r['seg_rank']}"

    def test_gtvn_borda(self, output, expected):
        rankings = expected[1]
        for team, r in rankings.items():
            actual = output['rankings'][team]['gtvn_borda']
            assert abs(actual - r['gtvn_borda']) < TOLERANCE, \
                f"{team}: gtvn_borda {actual} != {r['gtvn_borda']}"


class TestOverallRanking:
    def test_weighted_score(self, output, expected):
        rankings = expected[1]
        for team, r in rankings.items():
            actual = output['rankings'][team]['weighted_score']
            assert abs(actual - r['weighted_score']) < TOLERANCE, \
                f"{team}: weighted_score {actual} != {r['weighted_score']}"

    def test_final_ranking_order(self, output, expected):
        order = expected[2]
        assert output['final_ranking'] == order, \
            f"Ranking {output['final_ranking']} != {order}"

    def test_final_rank_values(self, output, expected):
        rankings = expected[1]
        for team, r in rankings.items():
            actual = output['rankings'][team]['final_rank']
            assert actual == r['final_rank'], \
                f"{team}: final_rank {actual} != {r['final_rank']}"


class TestBootstrapCI:
    def test_structure(self, output):
        for team in _get_teams():
            ci = output['bootstrap_ci'][team]
            for key in ('gtvp_mean_dsc', 'c_index',
                        'mean_balanced_accuracy'):
                assert key in ci, f"Missing CI key {key} for {team}"
                assert len(ci[key]) == 2
                assert ci[key][0] <= ci[key][1], \
                    f"{team}/{key}: lower > upper"

    def test_point_within_ci(self, output, expected):
        metrics = expected[0]
        for team in _get_teams():
            ci = output['bootstrap_ci'][team]
            for mk, ck in [('gtvp_mean_dsc', 'gtvp_mean_dsc'),
                           ('c_index', 'c_index'),
                           ('mean_balanced_accuracy',
                            'mean_balanced_accuracy')]:
                lo, hi = ci[ck]
                pt = metrics[team][mk]
                assert lo - 0.02 <= pt <= hi + 0.02, (
                    f"{team}: {mk} = {pt:.6f} outside CI "
                    f"[{lo:.6f}, {hi:.6f}]")

    def test_ci_values(self, output, expected_ci):
        for team in _get_teams():
            actual_ci = output['bootstrap_ci'][team]
            ref_ci = expected_ci[team]
            for key in ('gtvp_mean_dsc', 'c_index',
                        'mean_balanced_accuracy'):
                a_lo, a_hi = actual_ci[key]
                r_lo, r_hi = ref_ci[key]
                assert abs(a_lo - r_lo) < CI_TOLERANCE, (
                    f"{team}/{key} CI lower: {a_lo:.6f} vs {r_lo:.6f}")
                assert abs(a_hi - r_hi) < CI_TOLERANCE, (
                    f"{team}/{key} CI upper: {a_hi:.6f} vs {r_hi:.6f}")
