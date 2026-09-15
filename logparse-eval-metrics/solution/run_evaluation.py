#!/usr/bin/env python3
"""Run the Loghub-2.0 evaluation pipeline on all systems."""

import sys
sys.path.insert(0, '/solution')

import os
import pandas as pd
from evaluate import compute_ga_fga, compute_pa, compute_fta
from post_process import correct_template


def main():
    gt_dir = '/app/data/ground_truth'
    po_dir = '/app/data/parser_output'
    out_dir = '/app/results'
    os.makedirs(out_dir, exist_ok=True)

    # ── Compute metrics for each system ──
    results = []
    for fname in sorted(os.listdir(gt_dir)):
        if not fname.endswith('.csv'):
            continue
        system = fname.replace('.csv', '')

        gt = pd.read_csv(os.path.join(gt_dir, fname))
        parsed = pd.read_csv(os.path.join(po_dir, fname))

        # Align on non-null ground truth
        mask = gt['EventTemplate'].notna()
        gt_s = gt.loc[mask, 'EventTemplate'].reset_index(drop=True)
        pa_s = parsed.loc[mask, 'EventTemplate'].reset_index(drop=True)

        GA, FGA = compute_ga_fga(gt_s, pa_s)
        PA = compute_pa(gt_s, pa_s)
        FTA = compute_fta(gt_s, pa_s)

        results.append({
            'System': system,
            'GA': round(GA, 4),
            'FGA': round(FGA, 4),
            'PA': round(PA, 4),
            'FTA': round(FTA, 4),
        })
        print(f"{system}: GA={GA:.4f}  FGA={FGA:.4f}  PA={PA:.4f}  FTA={FTA:.4f}")

    pd.DataFrame(results).to_csv(
        os.path.join(out_dir, 'metrics.csv'), index=False)

    # ── Post-process all unique ground truth templates ──
    corrections = []
    for fname in sorted(os.listdir(gt_dir)):
        if not fname.endswith('.csv'):
            continue
        system = fname.replace('.csv', '')
        gt = pd.read_csv(os.path.join(gt_dir, fname))
        for tmpl in gt['EventTemplate'].dropna().unique():
            corrections.append({
                'System': system,
                'Original': tmpl,
                'Corrected': correct_template(tmpl),
            })

    pd.DataFrame(corrections).to_csv(
        os.path.join(out_dir, 'corrected_templates.csv'), index=False)

    print(f"\nResults written to {out_dir}/")


if __name__ == '__main__':
    main()
