#!/usr/bin/env python3
"""Generate synthetic HECKTOR challenge evaluation data with deterministic seed."""

import numpy as np
import csv
import os
import sqlite3
import tarfile
import zipfile
import shutil
import nibabel as nib
from scipy.ndimage import zoom

# Fixed rotation for oblique-affine patients (15-degree about z-axis)
_THETA = np.radians(15)
_OBLIQUE_ROT = np.array([
    [np.cos(_THETA), -np.sin(_THETA), 0],
    [np.sin(_THETA),  np.cos(_THETA), 0],
    [0,               0,              1]
])


def _make_affine(spacing, oblique=False):
    """Build a 4x4 affine; apply rotation if oblique."""
    aff = np.eye(4)
    if oblique:
        aff[:3, :3] = _OBLIQUE_ROT @ np.diag(spacing)
    else:
        aff[0, 0] = spacing[0]
        aff[1, 1] = spacing[1]
        aff[2, 2] = spacing[2]
    return aff


def main():
    np.random.seed(42)
    rng_extra = np.random.RandomState(99)

    N_PATIENTS = 20
    SHAPE = (32, 32, 32)

    for d in ['/app/data/ground_truth/segmentation',
              '/app/data/submissions', '/app/protocol', '/app/results']:
        os.makedirs(d, exist_ok=True)

    db_path = '/app/data/patients.db'
    # Remove any pre-existing database to avoid schema conflicts
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute('''CREATE TABLE patients (
        patient_id TEXT PRIMARY KEY,
        study_uid TEXT UNIQUE NOT NULL,
        site TEXT NOT NULL,
        age_at_diagnosis INTEGER,
        sex TEXT
    )''')

    cur.execute('''CREATE TABLE clinical_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id TEXT NOT NULL REFERENCES patients(patient_id),
        system TEXT NOT NULL,
        category TEXT NOT NULL,
        stage TEXT NOT NULL,
        assessment_method TEXT NOT NULL,
        assessment_date TEXT NOT NULL
    )''')

    cur.execute('''CREATE TABLE survival_followup (
        patient_id TEXT NOT NULL REFERENCES patients(patient_id),
        endpoint TEXT NOT NULL,
        duration_months REAL NOT NULL,
        event INTEGER NOT NULL,
        assessment_date TEXT
    )''')

    cur.execute('''CREATE TABLE treatment_protocol (
        patient_id TEXT NOT NULL REFERENCES patients(patient_id),
        modality TEXT NOT NULL,
        start_date TEXT,
        end_date TEXT,
        dose_gy REAL
    )''')

    conn.commit()

    # Verify schema immediately
    cols = [row[1] for row in conn.execute(
        "PRAGMA table_info(clinical_observations)").fetchall()]
    assert 'assessment_date' in cols, \
        "Schema error: assessment_date missing. Got columns: {}".format(cols)

    t_options = ['T1', 'T2', 'T3', 'T4']
    n_options = ['N0', 'N1', 'N2', 'N3']
    m_options = ['M0', 'M1']
    sites = ['ORL', 'CHUM', 'CHUS', 'HGJ', 'HMR']

    gt_masks = {}
    spacings = {}
    gt_staging_rows = []
    gt_survival_rows = []

    for i in range(1, N_PATIENTS + 1):
        pid = 'patient_{:03d}'.format(i)
        is_oblique = (11 <= i <= 15)

        spacing = [round(float(np.random.uniform(0.8, 1.5)), 4)
                   for _ in range(3)]
        spacings[pid] = spacing

        mask = np.zeros(SHAPE, dtype=np.uint8)
        center = np.array(SHAPE) // 2 + np.random.randint(-4, 4, 3)
        radius = np.random.randint(4, 8)
        z, y, x = np.ogrid[:SHAPE[0], :SHAPE[1], :SHAPE[2]]
        dist = ((z - center[0])**2 + (y - center[1])**2 +
                (x - center[2])**2).astype(float)
        mask[dist <= radius**2] = 1

        if i <= 14:
            center2 = center + np.array([8, 8, 8])
            center2 = np.clip(center2, 3, 28)
            radius2 = np.random.randint(2, 5)
            dist2 = ((z - center2[0])**2 + (y - center2[1])**2 +
                     (x - center2[2])**2).astype(float)
            mask[dist2 <= radius2**2] = 2

        affine = _make_affine(spacing, oblique=is_oblique)
        nii = nib.Nifti1Image(mask, affine)
        nib.save(nii,
                 '/app/data/ground_truth/segmentation/{}.nii.gz'.format(pid))
        gt_masks[pid] = mask

        # Patient record (study_uid and site use global RNG)
        study_uid = '1.2.840.{:06d}'.format(np.random.randint(100000, 999999))
        site = str(np.random.choice(sites))
        age = int(rng_extra.randint(40, 80))
        sex = str(rng_extra.choice(['M', 'F']))
        cur.execute('INSERT INTO patients VALUES (?, ?, ?, ?, ?)',
                    (pid, study_uid, site, age, sex))

        # AJCC8 pathological staging — original assessment (global RNG)
        t_stage = str(np.random.choice(t_options, p=[0.15, 0.3, 0.35, 0.2]))
        n_stage = str(np.random.choice(n_options, p=[0.25, 0.3, 0.3, 0.15]))
        m_stage = str(np.random.choice(m_options, p=[0.85, 0.15]))

        for cat, stg in [('T', t_stage), ('N', n_stage), ('M', m_stage)]:
            cur.execute(
                'INSERT INTO clinical_observations '
                '(patient_id, system, category, stage, assessment_method, '
                'assessment_date) VALUES (?, ?, ?, ?, ?, ?)',
                (pid, 'AJCC8', cat, stg, 'pathological', '2024-01-15'))

        gt_staging_rows.append({
            'patient_id': pid, 'T_stage': t_stage, 'N_stage': n_stage
        })

        # AJCC7 pathological staging (distractor — old edition, rng_extra)
        t7 = str(rng_extra.choice(t_options))
        n7 = str(rng_extra.choice(n_options))
        for cat, stg in [('T', t7), ('N', n7)]:
            cur.execute(
                'INSERT INTO clinical_observations '
                '(patient_id, system, category, stage, assessment_method, '
                'assessment_date) VALUES (?, ?, ?, ?, ?, ?)',
                (pid, 'AJCC7', cat, stg, 'pathological', '2023-06-10'))

        # AJCC8 clinical staging (distractor — wrong method, rng_extra)
        tc = str(rng_extra.choice(t_options))
        nc = str(rng_extra.choice(n_options))
        for cat, stg in [('T', tc), ('N', nc)]:
            cur.execute(
                'INSERT INTO clinical_observations '
                '(patient_id, system, category, stage, assessment_method, '
                'assessment_date) VALUES (?, ?, ?, ?, ?, ?)',
                (pid, 'AJCC8', cat, stg, 'clinical', '2024-02-01'))

        # UICC8 clinical staging (distractor — global RNG, same as original)
        t_stage_uicc = str(np.random.choice(t_options))
        n_stage_uicc = str(np.random.choice(n_options))
        for cat, stg in [('T', t_stage_uicc), ('N', n_stage_uicc)]:
            cur.execute(
                'INSERT INTO clinical_observations '
                '(patient_id, system, category, stage, assessment_method, '
                'assessment_date) VALUES (?, ?, ?, ?, ?, ?)',
                (pid, 'UICC8', cat, stg, 'clinical', '2024-01-20'))

        # Revised AJCC8 pathological staging for patients 16-20 (rng_extra)
        if i >= 16:
            rev_t = str(rng_extra.choice(
                [o for o in t_options if o != t_stage]))
            rev_n = str(rng_extra.choice(
                [o for o in n_options if o != n_stage]))
            for cat, stg in [('T', rev_t), ('N', rev_n)]:
                cur.execute(
                    'INSERT INTO clinical_observations '
                    '(patient_id, system, category, stage, assessment_method, '
                    'assessment_date) VALUES (?, ?, ?, ?, ?, ?)',
                    (pid, 'AJCC8', cat, stg, 'pathological', '2024-06-20'))

        # Treatment protocol (distractor, rng_extra)
        cur.execute(
            'INSERT INTO treatment_protocol VALUES (?, ?, ?, ?, ?)',
            (pid,
             str(rng_extra.choice(['RT', 'CRT', 'surgery'])),
             '2024-02-15', '2024-04-15',
             round(float(rng_extra.uniform(50, 70)), 1)))

        # Survival endpoints (global RNG, same as original)
        rfs_time = round(float(np.random.exponential(24)), 1)
        rfs_event = int(np.random.random() < 0.6)
        os_time = round(rfs_time + float(np.random.exponential(6)), 1)
        os_event = int(np.random.random() < 0.4)
        pfs_time = round(float(np.random.exponential(18)), 1)
        pfs_event = int(np.random.random() < 0.5)

        cur.execute('INSERT INTO survival_followup VALUES (?, ?, ?, ?, ?)',
                    (pid, 'recurrence_free', rfs_time, rfs_event, '2024-01-15'))
        cur.execute('INSERT INTO survival_followup VALUES (?, ?, ?, ?, ?)',
                    (pid, 'overall_survival', os_time, os_event, '2024-01-15'))
        cur.execute('INSERT INTO survival_followup VALUES (?, ?, ?, ?, ?)',
                    (pid, 'progression_free', pfs_time, pfs_event, '2024-01-15'))

        gt_survival_rows.append({
            'patient_id': pid,
            'time_months': rfs_time,
            'event': rfs_event
        })

    conn.commit()

    # Final schema verification before closing
    row_count = conn.execute(
        "SELECT COUNT(*) FROM clinical_observations").fetchone()[0]
    print("clinical_observations rows: {}".format(row_count))
    cols = [row[1] for row in conn.execute(
        "PRAGMA table_info(clinical_observations)").fetchall()]
    print("clinical_observations columns: {}".format(cols))
    assert 'assessment_date' in cols, \
        "FATAL: assessment_date column missing after data insert!"

    conn.close()

    # --- Team submissions (global RNG, same sequence as original) ---
    teams = {
        'team_alpha': {
            'seg_noise': 0.1, 'staging_acc': 0.85, 'survival_noise': 0.3,
            'missing_seg': [], 'missing_staging': False, 'nan_survival': [],
            'archive_type': 'tar.gz', 'high_res': False
        },
        'team_beta': {
            'seg_noise': 0.35, 'staging_acc': 0.75, 'survival_noise': 0.4,
            'missing_seg': ['patient_018', 'patient_019', 'patient_020'],
            'missing_staging': False,
            'nan_survival': ['patient_019', 'patient_020'],
            'archive_type': 'zip', 'high_res': False
        },
        'team_gamma': {
            'seg_noise': 0.15, 'staging_acc': 0.0, 'survival_noise': 0.5,
            'missing_seg': [], 'missing_staging': True, 'nan_survival': [],
            'archive_type': 'tar.bz2', 'high_res': True
        },
        'team_delta': {
            'seg_noise': 0.25, 'staging_acc': 0.70, 'survival_noise': 0.45,
            'missing_seg': [], 'missing_staging': False, 'nan_survival': [],
            'archive_type': 'tar.gz', 'high_res': False
        },
    }

    for team_name, params in teams.items():
        tmp_dir = '/tmp/sub_{}'.format(team_name)
        team_sub_dir = os.path.join(tmp_dir, team_name)
        seg_sub_dir = os.path.join(team_sub_dir, 'segmentation')
        os.makedirs(seg_sub_dir, exist_ok=True)

        for i in range(1, N_PATIENTS + 1):
            pid = 'patient_{:03d}'.format(i)
            is_oblique = (11 <= i <= 15)

            if pid in params['missing_seg']:
                continue

            gt = gt_masks[pid].copy()
            pred = gt.copy()
            noise_mask = np.random.random(SHAPE) < params['seg_noise']
            noise_labels = np.random.choice(
                [0, 1, 2], size=SHAPE, p=[0.6, 0.25, 0.15])
            pred[noise_mask] = noise_labels[noise_mask].astype(np.uint8)

            sp = spacings[pid]

            if params['high_res']:
                pred_hr = zoom(
                    pred.astype(np.float64), 2.0, order=0
                ).astype(np.uint8)
                hr_affine = _make_affine([s / 2.0 for s in sp],
                                         oblique=is_oblique)
                nii = nib.Nifti1Image(pred_hr, hr_affine)
            else:
                pred_affine = _make_affine(sp, oblique=is_oblique)
                nii = nib.Nifti1Image(pred, pred_affine)

            nib.save(nii, os.path.join(
                seg_sub_dir, '{}.nii.gz'.format(pid)))

        # Staging CSV
        if not params['missing_staging']:
            staging_rows = []
            for row in gt_staging_rows:
                pred_row = {'patient_id': row['patient_id']}
                for stage_col in ['T_stage', 'N_stage']:
                    if np.random.random() < params['staging_acc']:
                        pred_row[stage_col] = row[stage_col]
                    else:
                        options = (t_options if stage_col == 'T_stage'
                                   else n_options)
                        wrong = [o for o in options if o != row[stage_col]]
                        pred_row[stage_col] = str(np.random.choice(wrong))
                staging_rows.append(pred_row)

            with open(os.path.join(team_sub_dir, 'staging.csv'),
                      'w', newline='') as f:
                w = csv.DictWriter(
                    f, fieldnames=['patient_id', 'T_stage', 'N_stage'])
                w.writeheader()
                w.writerows(staging_rows)

        # Survival CSV
        survival_rows = []
        for row in gt_survival_rows:
            pid_s = row['patient_id']
            if pid_s in params['nan_survival']:
                survival_rows.append({
                    'patient_id': pid_s, 'risk_score': 'NaN'})
            else:
                base_risk = (1.0 / (row['time_months'] + 1)
                             if row['event'] else 0.3)
                noise = float(np.random.normal(0, params['survival_noise']))
                risk_score = round(
                    float(np.clip(base_risk + noise, 0, 1)), 4)
                survival_rows.append({
                    'patient_id': pid_s, 'risk_score': str(risk_score)})

        with open(os.path.join(team_sub_dir, 'survival.csv'),
                  'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=['patient_id', 'risk_score'])
            w.writeheader()
            w.writerows(survival_rows)

        # Create archive
        if params['archive_type'] == 'tar.gz':
            archive_path = '/app/data/submissions/{}.tar.gz'.format(team_name)
            with tarfile.open(archive_path, 'w:gz') as tar:
                tar.add(team_sub_dir, arcname=team_name)
        elif params['archive_type'] == 'zip':
            archive_path = '/app/data/submissions/{}.zip'.format(team_name)
            with zipfile.ZipFile(archive_path, 'w',
                                zipfile.ZIP_DEFLATED) as zf:
                for root, dirs_l, files in os.walk(team_sub_dir):
                    for fname in sorted(files):
                        file_path = os.path.join(root, fname)
                        arcname = os.path.relpath(file_path, tmp_dir)
                        zf.write(file_path, arcname)
        elif params['archive_type'] == 'tar.bz2':
            archive_path = '/app/data/submissions/{}.tar.bz2'.format(
                team_name)
            with tarfile.open(archive_path, 'w:bz2') as tar:
                tar.add(team_sub_dir, arcname=team_name)

        shutil.rmtree(tmp_dir)

    print("Data generation complete: {} patients, {} teams.".format(
        N_PATIENTS, len(teams)))


if __name__ == '__main__':
    main()
