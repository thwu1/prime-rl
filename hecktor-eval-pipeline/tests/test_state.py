
import json
import os
import csv
import sqlite3
import tarfile
import zipfile
import tempfile
import shutil
import numpy as np
import nibabel as nib
from scipy.ndimage import zoom, distance_transform_edt, binary_erosion
import pytest


DATA_DIR = '/app/data'
LEADERBOARD_PATH = '/app/results/leaderboard.json'
TOLERANCE = 1e-4
PATIENTS = ['patient_{:03d}'.format(i) for i in range(1, 21)]
TEAMS = ['team_alpha', 'team_beta', 'team_gamma', 'team_delta']


def load_csv(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def load_nifti(path):
    img = nib.load(path)
    data = np.asarray(img.dataobj).astype(np.uint8)
    spacing = tuple(float(s) for s in img.header.get_zooms()[:3])
    return data, spacing


# --- Reference implementations ---

def ref_aggregated_dice(gt_cache, pred_dir, patients, label):
    """Reference aggregated DSC for a single label."""
    total_tp = 0.0
    total_vol_sum = 0.0
    for pid in patients:
        gt, spacing = gt_cache[pid]
        vv = float(spacing[0] * spacing[1] * spacing[2])
        pred_path = os.path.join(pred_dir, '{}.nii.gz'.format(pid))
        if os.path.exists(pred_path):
            pred, _ = load_nifti(pred_path)
            if pred.shape != gt.shape:
                factors = tuple(
                    gs / ps for gs, ps in zip(gt.shape, pred.shape))
                pred = zoom(pred.astype(np.float64), factors,
                            order=0).astype(np.uint8)
        else:
            pred = np.zeros_like(gt)
        gt_bin = (gt == label).astype(np.float64)
        pred_bin = (pred == label).astype(np.float64)
        tp = np.sum(gt_bin * pred_bin) * vv
        gt_vol = np.sum(gt_bin) * vv
        pred_vol = np.sum(pred_bin) * vv
        total_tp += tp
        total_vol_sum += gt_vol + pred_vol
    if total_vol_sum == 0:
        return 1.0 if total_tp == 0 else 0.0
    return 2.0 * total_tp / total_vol_sum


def ref_hd95(pred_mask, gt_mask, spacing):
    """Reference HD95 in physical mm."""
    pred_surface = pred_mask & ~binary_erosion(pred_mask)
    gt_surface = gt_mask & ~binary_erosion(gt_mask)
    if not pred_surface.any() and not gt_surface.any():
        return 0.0
    if not pred_surface.any() or not gt_surface.any():
        dims = np.array(gt_mask.shape, dtype=np.float64) * np.array(
            spacing, dtype=np.float64)
        return float(np.sqrt(np.sum(dims ** 2)))
    dt_gt = distance_transform_edt(~gt_surface, sampling=spacing)
    dt_pred = distance_transform_edt(~pred_surface, sampling=spacing)
    d_pred_to_gt = dt_gt[pred_surface]
    d_gt_to_pred = dt_pred[gt_surface]
    all_distances = np.concatenate([d_pred_to_gt, d_gt_to_pred])
    return float(np.percentile(all_distances, 95))


def ref_balanced_accuracy(gt_rows, pred_rows, stage_col):
    """Reference balanced accuracy for a staging column."""
    if pred_rows is None:
        return 0.0
    gt_dict = {r['patient_id']: r[stage_col] for r in gt_rows}
    pred_dict = {r['patient_id']: r[stage_col] for r in pred_rows}
    classes = sorted(set(gt_dict.values()))
    recalls = []
    for cls in classes:
        gt_cls = [pid for pid, v in gt_dict.items() if v == cls]
        if len(gt_cls) == 0:
            continue
        correct = sum(1 for pid in gt_cls if pred_dict.get(pid) == cls)
        recalls.append(correct / len(gt_cls))
    return float(np.mean(recalls)) if recalls else 0.0


def ref_cindex(gt_survival, pred_survival):
    """Reference C-index with NaN handling."""
    gt_dict = {r['patient_id']: (float(r['time_months']), int(r['event']))
               for r in gt_survival}
    pred_dict = {}
    for r in pred_survival:
        try:
            risk = float(r['risk_score'])
        except (ValueError, KeyError):
            risk = float('nan')
        pred_dict[r['patient_id']] = risk
    patients_sorted = sorted(gt_dict.keys())
    concordant = 0
    discordant = 0
    tied = 0
    for i in range(len(patients_sorted)):
        for j in range(i + 1, len(patients_sorted)):
            pi, pj = patients_sorted[i], patients_sorted[j]
            ti, ei = gt_dict[pi]
            tj, ej = gt_dict[pj]
            ri = pred_dict.get(pi, 0.5)
            rj = pred_dict.get(pj, 0.5)
            comparable = False
            if ei == 1 and ej == 1:
                comparable = True
            elif ei == 1 and ej == 0 and ti < tj:
                comparable = True
            elif ej == 1 and ei == 0 and tj < ti:
                comparable = True
            if not comparable:
                continue
            if np.isnan(ri) or np.isnan(rj):
                discordant += 1
                continue
            if ti < tj and ei == 1:
                if ri > rj:
                    concordant += 1
                elif ri < rj:
                    discordant += 1
                else:
                    tied += 1
            elif tj < ti and ej == 1:
                if rj > ri:
                    concordant += 1
                elif rj < ri:
                    discordant += 1
                else:
                    tied += 1
            elif ti == tj and ei == 1 and ej == 1:
                tied += 1
    total = concordant + discordant + tied
    if total == 0:
        return 0.5
    return (concordant + 0.5 * tied) / total


# --- Fixtures ---

@pytest.fixture(scope='module')
def leaderboard():
    with open(LEADERBOARD_PATH) as f:
        return json.load(f)


@pytest.fixture(scope='module')
def gt_cache():
    gt_seg_dir = os.path.join(DATA_DIR, 'ground_truth', 'segmentation')
    cache = {}
    for pid in PATIENTS:
        cache[pid] = load_nifti(
            os.path.join(gt_seg_dir, '{}.nii.gz'.format(pid)))
    return cache


@pytest.fixture(scope='module')
def gt_staging():
    conn = sqlite3.connect(os.path.join(DATA_DIR, 'patients.db'))
    cur = conn.execute('''
        SELECT co.patient_id, co.category, co.stage
        FROM clinical_observations co
        INNER JOIN (
            SELECT patient_id, category, MAX(assessment_date) as max_date
            FROM clinical_observations
            WHERE system = 'AJCC8'
              AND assessment_method = 'pathological'
              AND category IN ('T', 'N')
            GROUP BY patient_id, category
        ) latest ON co.patient_id = latest.patient_id
            AND co.category = latest.category
            AND co.assessment_date = latest.max_date
        WHERE co.system = 'AJCC8'
          AND co.assessment_method = 'pathological'
          AND co.category IN ('T', 'N')
    ''')
    staging_dict = {}
    for pid, cat, stage in cur.fetchall():
        if pid not in staging_dict:
            staging_dict[pid] = {}
        staging_dict[pid][cat] = stage
    conn.close()
    return [{'patient_id': pid, 'T_stage': vals['T'], 'N_stage': vals['N']}
            for pid, vals in sorted(staging_dict.items())]


@pytest.fixture(scope='module')
def gt_survival():
    conn = sqlite3.connect(os.path.join(DATA_DIR, 'patients.db'))
    cur = conn.execute('''
        SELECT patient_id, duration_months, event
        FROM survival_followup
        WHERE endpoint = 'recurrence_free'
        ORDER BY patient_id
    ''')
    result = [{'patient_id': row[0], 'time_months': str(row[1]),
               'event': str(int(row[2]))}
              for row in cur.fetchall()]
    conn.close()
    return result


@pytest.fixture(scope='module')
def submission_dir():
    """Extract all team submission archives to a temp dir."""
    tmpdir = tempfile.mkdtemp(prefix='hecktor_test_')
    sub_dir = os.path.join(DATA_DIR, 'submissions')
    for f in sorted(os.listdir(sub_dir)):
        path = os.path.join(sub_dir, f)
        if not os.path.isfile(path):
            continue
        if f.endswith('.tar.gz') or f.endswith('.tgz'):
            with tarfile.open(path, 'r:gz') as tar:
                tar.extractall(tmpdir, filter='data')
        elif f.endswith('.tar.bz2'):
            with tarfile.open(path, 'r:bz2') as tar:
                tar.extractall(tmpdir, filter='data')
        elif f.endswith('.zip'):
            with zipfile.ZipFile(path, 'r') as zf:
                zf.extractall(tmpdir)
    yield tmpdir
    shutil.rmtree(tmpdir)


# --- Tests ---

class TestOutputExists:
    def test_leaderboard_file_exists(self):
        assert os.path.exists(LEADERBOARD_PATH), \
            'Leaderboard not found at {}'.format(LEADERBOARD_PATH)

    def test_valid_json(self, leaderboard):
        assert isinstance(leaderboard, dict)

    def test_has_rankings(self, leaderboard):
        assert 'rankings' in leaderboard
        assert isinstance(leaderboard['rankings'], list)
        assert len(leaderboard['rankings']) == 4


class TestRankingStructure:
    def test_required_fields(self, leaderboard):
        required = ['team', 'rank', 'dsc_aggregated', 'hd95_mean_mm',
                     'hd95_normalized', 'segmentation_score', 'staging_score',
                     'prognosis_score', 'weighted_score', 'consistency_score']
        for entry in leaderboard['rankings']:
            for field in required:
                assert field in entry, \
                    "Missing '{}' in entry for {}".format(
                        field, entry.get('team', '?'))

    def test_all_teams_present(self, leaderboard):
        teams = {e['team'] for e in leaderboard['rankings']}
        assert teams == set(TEAMS)

    def test_ranks_sequential(self, leaderboard):
        ranks = sorted([e['rank'] for e in leaderboard['rankings']])
        assert ranks == [1, 2, 3, 4]

    def test_ranking_order_by_weighted_score(self, leaderboard):
        ranked = sorted(leaderboard['rankings'], key=lambda x: x['rank'])
        for i in range(len(ranked) - 1):
            assert ranked[i]['weighted_score'] >= \
                ranked[i + 1]['weighted_score'] - TOLERANCE, \
                'Rank {} ({}) should have >= score than rank {} ({})'.format(
                    ranked[i]['rank'], ranked[i]['team'],
                    ranked[i + 1]['rank'], ranked[i + 1]['team'])


class TestDSCScores:
    def test_aggregated_dice_per_team(self, leaderboard, gt_cache,
                                      submission_dir):
        team_scores = {e['team']: e['dsc_aggregated']
                       for e in leaderboard['rankings']}
        for team in TEAMS:
            pred_seg_dir = os.path.join(
                submission_dir, team, 'segmentation')
            dice_1 = ref_aggregated_dice(
                gt_cache, pred_seg_dir, PATIENTS, 1)
            dice_2 = ref_aggregated_dice(
                gt_cache, pred_seg_dir, PATIENTS, 2)
            expected = (dice_1 + dice_2) / 2.0
            assert abs(team_scores[team] - expected) < TOLERANCE, \
                '{} dsc: expected {:.6f}, got {:.6f}'.format(
                    team, expected, team_scores[team])


class TestHD95Scores:
    def test_hd95_per_team(self, leaderboard, gt_cache, submission_dir):
        team_hd95 = {e['team']: e['hd95_mean_mm']
                     for e in leaderboard['rankings']}
        for team in TEAMS:
            pred_seg_dir = os.path.join(
                submission_dir, team, 'segmentation')
            hd95_1_vals = []
            hd95_2_vals = []
            for pid in PATIENTS:
                gt, spacing = gt_cache[pid]
                pred_path = os.path.join(
                    pred_seg_dir, '{}.nii.gz'.format(pid))
                if os.path.exists(pred_path):
                    pred, _ = load_nifti(pred_path)
                    if pred.shape != gt.shape:
                        factors = tuple(
                            gs / ps for gs, ps in
                            zip(gt.shape, pred.shape))
                        pred = zoom(pred.astype(np.float64), factors,
                                    order=0).astype(np.uint8)
                else:
                    pred = np.zeros_like(gt)
                gt_1 = (gt == 1)
                pred_1 = (pred == 1)
                hd95_1_vals.append(ref_hd95(pred_1, gt_1, spacing))
                gt_2 = (gt == 2)
                if gt_2.any():
                    pred_2 = (pred == 2)
                    hd95_2_vals.append(ref_hd95(pred_2, gt_2, spacing))
            mean_1 = float(np.mean(hd95_1_vals))
            mean_2 = (float(np.mean(hd95_2_vals))
                      if hd95_2_vals else 0.0)
            expected = (mean_1 + mean_2) / 2.0
            assert abs(team_hd95[team] - expected) < TOLERANCE, \
                '{} hd95: expected {:.6f}, got {:.6f}'.format(
                    team, expected, team_hd95[team])

    def test_hd95_normalized(self, leaderboard):
        for entry in leaderboard['rankings']:
            expected = 1.0 / (1.0 + entry['hd95_mean_mm'])
            assert abs(entry['hd95_normalized'] - expected) < TOLERANCE, \
                '{} hd95_norm: expected {:.6f}, got {:.6f}'.format(
                    entry['team'], expected, entry['hd95_normalized'])


class TestSegmentationScore:
    def test_composite_formula(self, leaderboard):
        for entry in leaderboard['rankings']:
            expected = (0.6 * entry['dsc_aggregated'] +
                        0.4 * entry['hd95_normalized'])
            assert abs(entry['segmentation_score'] - expected) < TOLERANCE, \
                '{} seg: expected {:.6f}, got {:.6f}'.format(
                    entry['team'], expected, entry['segmentation_score'])


class TestStagingScores:
    def test_balanced_accuracy_per_team(self, leaderboard, gt_staging,
                                        submission_dir):
        team_scores = {e['team']: e['staging_score']
                       for e in leaderboard['rankings']}
        for team in TEAMS:
            staging_path = os.path.join(
                submission_dir, team, 'staging.csv')
            if os.path.exists(staging_path):
                pred_staging = load_csv(staging_path)
            else:
                pred_staging = None
            ba_t = ref_balanced_accuracy(
                gt_staging, pred_staging, 'T_stage')
            ba_n = ref_balanced_accuracy(
                gt_staging, pred_staging, 'N_stage')
            expected = (ba_t + ba_n) / 2.0
            assert abs(team_scores[team] - expected) < TOLERANCE, \
                '{} staging: expected {:.6f}, got {:.6f}'.format(
                    team, expected, team_scores[team])


class TestPrognosisScores:
    def test_cindex_per_team(self, leaderboard, gt_survival,
                              submission_dir):
        team_scores = {e['team']: e['prognosis_score']
                       for e in leaderboard['rankings']}
        for team in TEAMS:
            pred_path = os.path.join(
                submission_dir, team, 'survival.csv')
            pred_survival = load_csv(pred_path)
            expected = ref_cindex(gt_survival, pred_survival)
            assert abs(team_scores[team] - expected) < TOLERANCE, \
                '{} prognosis: expected {:.6f}, got {:.6f}'.format(
                    team, expected, team_scores[team])


class TestWeightedScores:
    def test_weighted_formula(self, leaderboard):
        for entry in leaderboard['rankings']:
            expected = (0.25 * entry['segmentation_score'] +
                        0.35 * entry['staging_score'] +
                        0.40 * entry['prognosis_score'])
            assert abs(entry['weighted_score'] - expected) < TOLERANCE, \
                '{} weighted: expected {:.6f}, got {:.6f}'.format(
                    entry['team'], expected, entry['weighted_score'])


class TestConsistencyScores:
    def test_consistency_formula(self, leaderboard):
        for entry in leaderboard['rankings']:
            unweighted = (entry['segmentation_score'] +
                          entry['staging_score'] +
                          entry['prognosis_score']) / 3.0
            expected = abs(entry['weighted_score'] - unweighted)
            assert abs(entry['consistency_score'] - expected) < TOLERANCE, \
                '{} consistency: expected {:.6f}, got {:.6f}'.format(
                    entry['team'], expected, entry['consistency_score'])


class TestMissingSubmissions:
    def test_missing_staging_yields_zero(self, leaderboard):
        gamma = [e for e in leaderboard['rankings']
                 if e['team'] == 'team_gamma'][0]
        assert abs(gamma['staging_score']) < TOLERANCE, \
            'team_gamma missing staging, expected 0, got {}'.format(
                gamma['staging_score'])

    def test_missing_segmentation_penalizes_dsc(self, leaderboard):
        alpha = [e for e in leaderboard['rankings']
                 if e['team'] == 'team_alpha'][0]
        beta = [e for e in leaderboard['rankings']
                if e['team'] == 'team_beta'][0]
        assert alpha['dsc_aggregated'] > beta['dsc_aggregated'], \
            'team_alpha (all segs) should outscore team_beta (missing) in DSC'


class TestStatisticalAnalysis:
    def test_statistical_analysis_present(self, leaderboard):
        assert 'statistical_analysis' in leaderboard, \
            'Missing statistical_analysis'
        stats = leaderboard['statistical_analysis']
        assert 'pairwise_comparisons' in stats, \
            'Missing pairwise_comparisons'

    def test_six_pairwise_comparisons(self, leaderboard):
        comps = leaderboard['statistical_analysis']['pairwise_comparisons']
        assert len(comps) >= 6, \
            'Expected >= 6 pairwise comparisons, got {}'.format(len(comps))

    def test_comparison_structure(self, leaderboard):
        comps = leaderboard['statistical_analysis']['pairwise_comparisons']
        for comp in comps:
            assert 'team_a' in comp, 'Missing team_a'
            assert 'team_b' in comp, 'Missing team_b'
            assert 'ci_lower' in comp, 'Missing ci_lower'
            assert 'ci_upper' in comp, 'Missing ci_upper'
            assert 'significant' in comp, 'Missing significant'

    def test_ci_bounds_valid(self, leaderboard):
        comps = leaderboard['statistical_analysis']['pairwise_comparisons']
        for comp in comps:
            assert comp['ci_lower'] <= comp['ci_upper'], \
                'CI lower ({}) > upper ({}) for {} vs {}'.format(
                    comp['ci_lower'], comp['ci_upper'],
                    comp.get('team_a'), comp.get('team_b'))
            assert isinstance(comp['significant'], bool), \
                'significant should be bool for {} vs {}'.format(
                    comp.get('team_a'), comp.get('team_b'))

    def test_all_team_pairs_covered(self, leaderboard):
        comps = leaderboard['statistical_analysis']['pairwise_comparisons']
        pairs = set()
        for comp in comps:
            pair = tuple(sorted([comp['team_a'], comp['team_b']]))
            pairs.add(pair)
        from itertools import combinations
        expected_pairs = set(
            tuple(sorted(p)) for p in combinations(TEAMS, 2))
        assert pairs == expected_pairs, \
            'Missing team pairs: {}'.format(expected_pairs - pairs)
