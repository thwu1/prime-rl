#!/usr/bin/env python3
"""HECKTOR Challenge Evaluation Pipeline."""

import numpy as np
import json
import csv
import os
import sqlite3
import tarfile
import zipfile
import tempfile
import shutil
from itertools import combinations
import nibabel as nib
from scipy.ndimage import zoom, distance_transform_edt, binary_erosion


def load_csv(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def load_nifti(path):
    """Load a NIfTI file, return uint8 data array and voxel spacing."""
    img = nib.load(path)
    data = np.asarray(img.dataobj).astype(np.uint8)
    spacing = tuple(float(s) for s in img.header.get_zooms()[:3])
    return data, spacing


def load_patient_data(db_path):
    """Load staging and survival ground truth from normalized SQLite DB."""
    conn = sqlite3.connect(db_path)

    # Latest AJCC8 pathological T and N staging per patient
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
    staging = [{'patient_id': pid, 'T_stage': vals['T'], 'N_stage': vals['N']}
               for pid, vals in sorted(staging_dict.items())]

    # Recurrence-free survival endpoint only
    cur = conn.execute('''
        SELECT patient_id, duration_months, event
        FROM survival_followup
        WHERE endpoint = 'recurrence_free'
        ORDER BY patient_id
    ''')
    survival = [{'patient_id': row[0], 'time_months': str(row[1]),
                 'event': str(int(row[2]))}
                for row in cur.fetchall()]

    conn.close()
    return staging, survival


def extract_submission(archive_path, output_dir):
    """Extract a submission archive, detecting format from extension."""
    if archive_path.endswith('.tar.gz') or archive_path.endswith('.tgz'):
        with tarfile.open(archive_path, 'r:gz') as tar:
            tar.extractall(output_dir, filter='data')
    elif archive_path.endswith('.tar.bz2'):
        with tarfile.open(archive_path, 'r:bz2') as tar:
            tar.extractall(output_dir, filter='data')
    elif archive_path.endswith('.zip'):
        with zipfile.ZipFile(archive_path, 'r') as zf:
            zf.extractall(output_dir)
    else:
        raise ValueError('Unknown archive format: {}'.format(archive_path))


def resample_if_needed(pred, gt_shape):
    """Resample prediction to match GT shape using nearest-neighbor."""
    if pred.shape != gt_shape:
        factors = tuple(gs / ps for gs, ps in zip(gt_shape, pred.shape))
        pred = zoom(pred.astype(np.float64), factors, order=0).astype(np.uint8)
    return pred


def compute_aggregated_dice(gt_cache, pred_dir, patients, label):
    """Compute aggregated (volume-weighted) Dice for a single label."""
    total_tp = 0.0
    total_vol_sum = 0.0
    for pid in patients:
        gt, spacing = gt_cache[pid]
        vv = float(spacing[0] * spacing[1] * spacing[2])

        pred_path = os.path.join(pred_dir, '{}.nii.gz'.format(pid))
        if os.path.exists(pred_path):
            pred, _ = load_nifti(pred_path)
            pred = resample_if_needed(pred, gt.shape)
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


def compute_hd95(pred_mask, gt_mask, spacing):
    """Compute 95th percentile symmetric Hausdorff distance in mm."""
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


def compute_balanced_accuracy(gt_rows, pred_rows, stage_col):
    """Compute balanced accuracy for a staging column."""
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


def compute_cindex(gt_survival, pred_survival):
    """Compute Harrell's C-index with NaN risk score handling."""
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


def main():
    data_dir = '/app/data'
    gt_seg_dir = os.path.join(data_dir, 'ground_truth', 'segmentation')

    # Load ground truth NIfTI files and cache data + spacing
    gt_cache = {}
    patients = sorted([
        f.replace('.nii.gz', '')
        for f in os.listdir(gt_seg_dir)
        if f.endswith('.nii.gz')
    ])
    for pid in patients:
        gt_cache[pid] = load_nifti(
            os.path.join(gt_seg_dir, '{}.nii.gz'.format(pid)))

    # Load clinical data from normalized database
    db_path = os.path.join(data_dir, 'patients.db')
    gt_staging, gt_survival = load_patient_data(db_path)

    # Extract all team submissions (mixed archive formats)
    work_dir = tempfile.mkdtemp(prefix='hecktor_eval_')
    sub_dir = os.path.join(data_dir, 'submissions')
    teams = []
    for f in sorted(os.listdir(sub_dir)):
        archive_path = os.path.join(sub_dir, f)
        if os.path.isfile(archive_path):
            extract_submission(archive_path, work_dir)
            team_name = f.split('.')[0]
            teams.append(team_name)

    # --- Per-team evaluation ---
    results = []
    patient_metrics = {}

    for team in teams:
        team_dir = os.path.join(work_dir, team)
        seg_dir = os.path.join(team_dir, 'segmentation')

        # Aggregated DSC per label
        dice_1 = compute_aggregated_dice(gt_cache, seg_dir, patients, 1)
        dice_2 = compute_aggregated_dice(gt_cache, seg_dir, patients, 2)
        dsc_agg = (dice_1 + dice_2) / 2.0

        # HD95 per patient per label
        hd95_values_1 = []
        hd95_values_2 = []
        per_patient_hd95 = {}

        for pid in patients:
            gt, spacing = gt_cache[pid]

            pred_path = os.path.join(seg_dir, '{}.nii.gz'.format(pid))
            if os.path.exists(pred_path):
                pred, _ = load_nifti(pred_path)
                pred = resample_if_needed(pred, gt.shape)
            else:
                pred = np.zeros_like(gt)

            h1 = compute_hd95((pred == 1), (gt == 1), spacing)
            hd95_values_1.append(h1)
            per_patient_hd95[pid] = {'hd95_1': h1, 'hd95_2': None}

            gt_bin_2 = (gt == 2)
            if gt_bin_2.any():
                h2 = compute_hd95((pred == 2), gt_bin_2, spacing)
                hd95_values_2.append(h2)
                per_patient_hd95[pid]['hd95_2'] = h2

        mean_hd95_1 = float(np.mean(hd95_values_1))
        mean_hd95_2 = (float(np.mean(hd95_values_2))
                       if hd95_values_2 else 0.0)
        mean_hd95 = (mean_hd95_1 + mean_hd95_2) / 2.0
        hd95_normalized = 1.0 / (1.0 + mean_hd95)

        segmentation_score = 0.6 * dsc_agg + 0.4 * hd95_normalized

        # Staging
        staging_path = os.path.join(team_dir, 'staging.csv')
        pred_staging = (load_csv(staging_path)
                        if os.path.exists(staging_path) else None)
        ba_t = compute_balanced_accuracy(gt_staging, pred_staging, 'T_stage')
        ba_n = compute_balanced_accuracy(gt_staging, pred_staging, 'N_stage')
        staging_score = (ba_t + ba_n) / 2.0

        # Prognosis
        pred_survival = load_csv(os.path.join(team_dir, 'survival.csv'))
        prognosis_score = compute_cindex(gt_survival, pred_survival)

        # Weighted score
        weighted = (0.25 * segmentation_score + 0.35 * staging_score +
                    0.40 * prognosis_score)
        unweighted = (segmentation_score + staging_score +
                      prognosis_score) / 3.0
        consistency = abs(weighted - unweighted)

        results.append({
            'team': team,
            'dsc_aggregated': round(dsc_agg, 6),
            'hd95_mean_mm': round(mean_hd95, 6),
            'hd95_normalized': round(hd95_normalized, 6),
            'segmentation_score': round(segmentation_score, 6),
            'staging_score': round(staging_score, 6),
            'prognosis_score': round(prognosis_score, 6),
            'weighted_score': round(weighted, 6),
            'consistency_score': round(consistency, 6),
        })

        # Pre-compute per-patient metrics for bootstrap
        gt_staging_dict = {r['patient_id']: r for r in gt_staging}
        pred_staging_dict = ({r['patient_id']: r for r in pred_staging}
                             if pred_staging else {})
        gt_surv_dict = {r['patient_id']: r for r in gt_survival}
        pred_surv_dict = {}
        for r in pred_survival:
            try:
                risk = float(r['risk_score'])
            except (ValueError, KeyError):
                risk = float('nan')
            pred_surv_dict[r['patient_id']] = risk

        per_patient = []
        for pid in patients:
            gt, spacing = gt_cache[pid]
            vv = float(spacing[0] * spacing[1] * spacing[2])

            pred_path = os.path.join(seg_dir, '{}.nii.gz'.format(pid))
            if os.path.exists(pred_path):
                pred, _ = load_nifti(pred_path)
                pred = resample_if_needed(pred, gt.shape)
            else:
                pred = np.zeros_like(gt)

            m = {}
            for label in [1, 2]:
                gt_bin = (gt == label).astype(np.float64)
                pred_bin = (pred == label).astype(np.float64)
                m['tp_{}'.format(label)] = float(
                    np.sum(gt_bin * pred_bin) * vv)
                m['vol_sum_{}'.format(label)] = float(
                    (np.sum(gt_bin) + np.sum(pred_bin)) * vv)

            m['hd95_1'] = per_patient_hd95[pid]['hd95_1']
            m['hd95_2'] = per_patient_hd95[pid]['hd95_2']

            m['t_gt'] = gt_staging_dict[pid]['T_stage']
            m['n_gt'] = gt_staging_dict[pid]['N_stage']
            m['t_correct'] = int(
                pred_staging_dict.get(pid, {}).get('T_stage') == m['t_gt']
            ) if pred_staging else 0
            m['n_correct'] = int(
                pred_staging_dict.get(pid, {}).get('N_stage') == m['n_gt']
            ) if pred_staging else 0

            m['time'] = float(gt_surv_dict[pid]['time_months'])
            m['event'] = int(gt_surv_dict[pid]['event'])
            m['risk'] = pred_surv_dict.get(pid, 0.5)
            per_patient.append(m)

        patient_metrics[team] = per_patient

    # Rank: descending weighted, ascending consistency for ties
    results.sort(key=lambda x: (-x['weighted_score'], x['consistency_score']))
    for i, r in enumerate(results):
        r['rank'] = i + 1

    # --- Bootstrap confidence intervals ---
    def weighted_score_from_indices(team, indices):
        pp = patient_metrics[team]
        selected = [pp[idx] for idx in indices]

        # DSC
        dice_scores = []
        for label in [1, 2]:
            t_tp = sum(s['tp_{}'.format(label)] for s in selected)
            t_vs = sum(s['vol_sum_{}'.format(label)] for s in selected)
            if t_vs == 0:
                dice_scores.append(1.0)
            else:
                dice_scores.append(2.0 * t_tp / t_vs)
        dsc = float(np.mean(dice_scores))

        # HD95
        hd95_1_vals = [s['hd95_1'] for s in selected]
        hd95_2_vals = [s['hd95_2'] for s in selected
                       if s['hd95_2'] is not None]
        m_hd95_1 = float(np.mean(hd95_1_vals))
        m_hd95_2 = (float(np.mean(hd95_2_vals))
                    if hd95_2_vals else 0.0)
        m_hd95 = (m_hd95_1 + m_hd95_2) / 2.0
        hd95_n = 1.0 / (1.0 + m_hd95)

        seg = 0.6 * dsc + 0.4 * hd95_n

        # Balanced accuracy
        t_classes = sorted(set(s['t_gt'] for s in selected))
        n_classes = sorted(set(s['n_gt'] for s in selected))
        t_recalls = []
        for cls in t_classes:
            cls_s = [s for s in selected if s['t_gt'] == cls]
            if cls_s:
                t_recalls.append(
                    sum(s['t_correct'] for s in cls_s) / len(cls_s))
        n_recalls = []
        for cls in n_classes:
            cls_s = [s for s in selected if s['n_gt'] == cls]
            if cls_s:
                n_recalls.append(
                    sum(s['n_correct'] for s in cls_s) / len(cls_s))
        ba_t = float(np.mean(t_recalls)) if t_recalls else 0.0
        ba_n = float(np.mean(n_recalls)) if n_recalls else 0.0
        stg = (ba_t + ba_n) / 2.0

        # C-index
        concordant = 0
        discordant = 0
        tied_r = 0
        for a in range(len(selected)):
            for b in range(a + 1, len(selected)):
                sa, sb = selected[a], selected[b]
                ta, ea, ra = sa['time'], sa['event'], sa['risk']
                tb, eb, rb = sb['time'], sb['event'], sb['risk']
                comp = False
                if ea == 1 and eb == 1:
                    comp = True
                elif ea == 1 and eb == 0 and ta < tb:
                    comp = True
                elif eb == 1 and ea == 0 and tb < ta:
                    comp = True
                if not comp:
                    continue
                if np.isnan(ra) or np.isnan(rb):
                    discordant += 1
                    continue
                if ta < tb and ea == 1:
                    if ra > rb:
                        concordant += 1
                    elif ra < rb:
                        discordant += 1
                    else:
                        tied_r += 1
                elif tb < ta and eb == 1:
                    if rb > ra:
                        concordant += 1
                    elif rb < ra:
                        discordant += 1
                    else:
                        tied_r += 1
                elif ta == tb and ea == 1 and eb == 1:
                    tied_r += 1
        tot = concordant + discordant + tied_r
        prog = (concordant + 0.5 * tied_r) / tot if tot > 0 else 0.5

        return 0.25 * seg + 0.35 * stg + 0.40 * prog

    rng = np.random.RandomState(123)
    n_bootstrap = 1000
    pairwise_comparisons = []

    for ta, tb in combinations(teams, 2):
        diffs = []
        for _ in range(n_bootstrap):
            indices = rng.choice(len(patients), size=len(patients),
                                 replace=True)
            sa = weighted_score_from_indices(ta, indices)
            sb = weighted_score_from_indices(tb, indices)
            diffs.append(sa - sb)
        diffs.sort()
        ci_lo = float(diffs[25])
        ci_hi = float(diffs[974])
        sig = bool(ci_lo > 0 or ci_hi < 0)
        pairwise_comparisons.append({
            'team_a': ta,
            'team_b': tb,
            'ci_lower': round(ci_lo, 6),
            'ci_upper': round(ci_hi, 6),
            'significant': sig,
        })

    shutil.rmtree(work_dir)

    # Assemble output
    leaderboard = {
        'rankings': results,
        'statistical_analysis': {
            'pairwise_comparisons': pairwise_comparisons,
        }
    }

    os.makedirs('/app/results', exist_ok=True)
    with open('/app/results/leaderboard.json', 'w') as f:
        json.dump(leaderboard, f, indent=2)

    print('Evaluation complete.')
    for r in results:
        print('  #{rank} {team}: weighted={weighted_score:.4f}'.format(**r))


if __name__ == '__main__':
    main()
