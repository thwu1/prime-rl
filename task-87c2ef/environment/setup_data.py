#!/usr/bin/env python3
"""Generate synthetic evaluation data for the multi-task clinical challenge."""

import random
import csv
import json
import os
import math
import sqlite3


def weighted_choice(population, weights):
    return random.choices(population, weights=weights, k=1)[0]


def poisson_sample(lam):
    if lam <= 0:
        return 0
    L = math.exp(-lam)
    k = 0
    p = 1.0
    while True:
        k += 1
        p *= random.random()
        if p < L:
            break
    return k - 1


def write_csv(filepath, fieldnames, rows):
    with open(filepath, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    random.seed(42)

    teams = ['team_a', 'team_b', 'team_c', 'team_d', 'team_e', 'team_f']
    patients = [f'P{i:03d}' for i in range(1, 21)]
    n_patients = 20

    os.makedirs('/app/data/ground_truth', exist_ok=True)
    for team in teams:
        os.makedirs(f'/app/data/submissions/{team}', exist_ok=True)
    os.makedirs('/app/docs', exist_ok=True)
    os.makedirs('/app/output', exist_ok=True)

    # === Ground Truth ===

    t_classes = ['T1', 'T2', 'T3', 'T4']
    n_classes = ['N0', 'N1', 'N2', 'N3']

    t_stages = [weighted_choice(t_classes, [0.15, 0.30, 0.35, 0.20])
                for _ in range(n_patients)]
    n_stages = [weighted_choice(n_classes, [0.20, 0.25, 0.35, 0.20])
                for _ in range(n_patients)]

    event_times = [round(random.expovariate(1.0 / 24.0), 2)
                   for _ in range(n_patients)]
    event_observed = [1 if random.random() < 0.6 else 0
                      for _ in range(n_patients)]

    has_gtvn = [random.random() < 0.8 for _ in range(n_patients)]
    n_gtvn_lesions = [random.randint(1, 3) if h else 0 for h in has_gtvn]

    write_csv('/app/data/ground_truth/staging.csv',
              ['patient_id', 't_stage', 'n_stage'],
              [{'patient_id': patients[i], 't_stage': t_stages[i],
                'n_stage': n_stages[i]} for i in range(n_patients)])

    write_csv('/app/data/ground_truth/survival.csv',
              ['patient_id', 'event_time', 'event_observed'],
              [{'patient_id': patients[i], 'event_time': event_times[i],
                'event_observed': event_observed[i]}
               for i in range(n_patients)])

    write_csv('/app/data/ground_truth/segmentation_meta.csv',
              ['patient_id', 'has_gtvn', 'n_gtvn_lesions'],
              [{'patient_id': patients[i], 'has_gtvn': has_gtvn[i],
                'n_gtvn_lesions': n_gtvn_lesions[i]}
               for i in range(n_patients)])

    # === Team Submissions ===
    quality = {
        'team_a': 0.82, 'team_b': 0.73, 'team_c': 0.88,
        'team_d': 0.68, 'team_e': None, 'team_f': 0.78
    }

    for team in teams:
        # --- Segmentation ---
        if team != 'team_e':
            q = quality[team]
            seg_rows = []
            for i in range(n_patients):
                gt_vol = 5000 + random.random() * 45000
                pred_vol = gt_vol * max(0.1, q + random.gauss(0, 0.08))
                vol_sum_p = gt_vol + pred_vol
                dice_factor = max(0.1, min(0.99, q + random.gauss(0, 0.05)))
                tp_p = dice_factor * vol_sum_p / 2.0

                if has_gtvn[i]:
                    gt_vol_n = 2000 + random.random() * 28000
                    pred_vol_n = gt_vol_n * max(0.1, q + random.gauss(0, 0.12))
                    vol_sum_n = gt_vol_n + pred_vol_n
                    dice_n = max(0.05, min(0.99, q + random.gauss(0, 0.08)))
                    tp_n = dice_n * vol_sum_n / 2.0

                    nl = n_gtvn_lesions[i]
                    tp_d = sum(1 for _ in range(nl)
                              if random.random() < min(q + 0.1, 1.0))
                    fn_d = nl - tp_d
                    fp_d = poisson_sample(max(0.01, 0.3 * (1 - q)))
                else:
                    vol_sum_n = 0.0
                    if random.random() < 0.2 * (1 - q):
                        vol_sum_n = random.uniform(100, 2000)
                    tp_n = 0.0
                    tp_d = 0
                    fn_d = 0
                    fp_d = 1 if random.random() < 0.15 * (1 - q) else 0

                seg_rows.append({
                    'patient_id': patients[i],
                    'tp_gtvp': round(tp_p, 6),
                    'vol_sum_gtvp': round(vol_sum_p, 6),
                    'tp_gtvn': round(tp_n, 6),
                    'vol_sum_gtvn': round(vol_sum_n, 6),
                    'tp_detect': tp_d,
                    'fp_detect': fp_d,
                    'fn_detect': fn_d
                })

            write_csv(
                f'/app/data/submissions/{team}/segmentation.csv',
                ['patient_id', 'tp_gtvp', 'vol_sum_gtvp', 'tp_gtvn',
                 'vol_sum_gtvn', 'tp_detect', 'fp_detect', 'fn_detect'],
                seg_rows)

        # --- Survival ---
        surv_rows = []
        for i in range(n_patients):
            if team == 'team_f' and i in [3, 7, 15]:
                surv_rows.append({
                    'patient_id': patients[i], 'predicted_risk': ''})
            else:
                true_risk = -event_times[i]
                noise = random.gauss(0, 8)
                surv_rows.append({
                    'patient_id': patients[i],
                    'predicted_risk': round(true_risk + noise, 6)})

        write_csv(f'/app/data/submissions/{team}/survival.csv',
                  ['patient_id', 'predicted_risk'], surv_rows)

        # --- Staging ---
        stage_rows = []
        for i in range(n_patients):
            true_t = t_classes.index(t_stages[i])
            true_n = n_classes.index(n_stages[i])

            if team == 'team_d':
                off_t = weighted_choice(
                    [-2, -1, 0, 1, 2], [0.05, 0.15, 0.40, 0.25, 0.15])
                off_n = weighted_choice(
                    [-2, -1, 0, 1, 2], [0.05, 0.15, 0.40, 0.25, 0.15])
            else:
                off_t = weighted_choice([-1, 0, 1], [0.10, 0.70, 0.20])
                off_n = weighted_choice([-1, 0, 1], [0.10, 0.70, 0.20])

            pred_t = max(0, min(3, true_t + off_t))
            pred_n = max(0, min(3, true_n + off_n))

            stage_rows.append({
                'patient_id': patients[i],
                'predicted_t': t_classes[pred_t],
                'predicted_n': n_classes[pred_n]
            })

        write_csv(f'/app/data/submissions/{team}/staging.csv',
                  ['patient_id', 'predicted_t', 'predicted_n'], stage_rows)

    # === SQLite Database ===
    conn = sqlite3.connect('/app/data/challenge.db')
    c = conn.cursor()

    c.execute('CREATE TABLE ground_truth_staging ('
              'patient_id TEXT PRIMARY KEY, t_stage TEXT, n_stage TEXT)')
    c.execute('CREATE TABLE ground_truth_survival ('
              'patient_id TEXT PRIMARY KEY, event_time REAL, '
              'event_observed INTEGER)')
    c.execute('CREATE TABLE segmentation_meta ('
              'patient_id TEXT PRIMARY KEY, has_gtvn INTEGER, '
              'n_gtvn_lesions INTEGER)')
    c.execute('CREATE TABLE submissions_segmentation ('
              'team TEXT, patient_id TEXT, tp_gtvp REAL, vol_sum_gtvp REAL, '
              'tp_gtvn REAL, vol_sum_gtvn REAL, tp_detect INTEGER, '
              'fp_detect INTEGER, fn_detect INTEGER, '
              'PRIMARY KEY (team, patient_id))')
    c.execute('CREATE TABLE submissions_survival ('
              'team TEXT, patient_id TEXT, predicted_risk TEXT, '
              'PRIMARY KEY (team, patient_id))')
    c.execute('CREATE TABLE submissions_staging ('
              'team TEXT, patient_id TEXT, predicted_t TEXT, '
              'predicted_n TEXT, PRIMARY KEY (team, patient_id))')

    for i in range(n_patients):
        c.execute('INSERT INTO ground_truth_staging VALUES (?,?,?)',
                  (patients[i], t_stages[i], n_stages[i]))
        c.execute('INSERT INTO ground_truth_survival VALUES (?,?,?)',
                  (patients[i], event_times[i], event_observed[i]))
        c.execute('INSERT INTO segmentation_meta VALUES (?,?,?)',
                  (patients[i], int(has_gtvn[i]), n_gtvn_lesions[i]))

    for team in teams:
        seg_path = f'/app/data/submissions/{team}/segmentation.csv'
        if os.path.exists(seg_path):
            with open(seg_path) as f:
                for row in csv.DictReader(f):
                    c.execute(
                        'INSERT INTO submissions_segmentation '
                        'VALUES (?,?,?,?,?,?,?,?,?)',
                        (team, row['patient_id'], float(row['tp_gtvp']),
                         float(row['vol_sum_gtvp']), float(row['tp_gtvn']),
                         float(row['vol_sum_gtvn']), int(row['tp_detect']),
                         int(row['fp_detect']), int(row['fn_detect'])))

        with open(f'/app/data/submissions/{team}/survival.csv') as f:
            for row in csv.DictReader(f):
                risk = row['predicted_risk']
                c.execute('INSERT INTO submissions_survival VALUES (?,?,?)',
                          (team, row['patient_id'],
                           None if risk == '' else risk))

        with open(f'/app/data/submissions/{team}/staging.csv') as f:
            for row in csv.DictReader(f):
                c.execute(
                    'INSERT INTO submissions_staging VALUES (?,?,?,?)',
                    (team, row['patient_id'],
                     row['predicted_t'], row['predicted_n']))

    conn.commit()
    conn.close()

    print("Data generation complete.")
    print(f"  Teams: {teams}")
    print(f"  Patients: {n_patients}")
    print("  SQLite database: /app/data/challenge.db")


if __name__ == '__main__':
    main()
