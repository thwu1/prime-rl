#!/usr/bin/env python3
"""Generate the final evaluation report as JSON from the pipeline database."""
import json
import os
import sqlite3

DB_PATH = '/app/pipeline.db'
OUTPUT_PATH = '/app/output/results.json'
NUTRIENTS = ['energy', 'fat', 'saturates', 'sugars', 'protein', 'salt']
FSA_NUTRIENTS = ['fat', 'saturates', 'sugars', 'salt']
FSA_CLASSES = ['green', 'amber', 'red']


def compute_f1(pred_labels, true_labels, cls):
    """Compute F1 score for a single class."""
    tp = sum(1 for p, t in zip(pred_labels, true_labels) if p == cls and t == cls)
    fp = sum(1 for p, t in zip(pred_labels, true_labels) if p == cls and t != cls)
    fn = sum(1 for p, t in zip(pred_labels, true_labels) if p != cls and t == cls)
    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    if prec + rec == 0:
        return 0.0
    return 2 * prec * rec / (prec + rec)


def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    rd = int(c.execute(
        "SELECT value FROM config WHERE key='round_digits'").fetchone()[0])

    systems = [r[0] for r in c.execute(
        'SELECT DISTINCT system_name FROM tolerance_results '
        'ORDER BY system_name')]

    # --- Tolerance accuracy ---
    tolerance_accuracy = {}
    for sys in systems:
        overall = c.execute(
            'SELECT CAST(SUM(within_tolerance) AS REAL) / COUNT(*) '
            'FROM tolerance_results WHERE system_name=?',
            (sys,)).fetchone()[0]

        per_nutrient = {}
        row = c.execute(
            'SELECT CAST(SUM(within_tolerance) AS REAL) / COUNT(*) '
            'FROM tolerance_results WHERE system_name=?',
            (sys,)).fetchone()
        for nut in NUTRIENTS:
            per_nutrient[nut] = round(row[0], rd)

        tolerance_accuracy[sys] = {
            'overall': round(overall, rd),
            'per_nutrient': per_nutrient
        }

    # --- FSA evaluation ---
    fsa_evaluation = {}
    for sys in systems:
        per_nut_f1 = {}
        for nut in FSA_NUTRIENTS:
            rows = c.execute(
                'SELECT true_label, predicted_label FROM fsa_results '
                'WHERE system_name=? AND nutrient=?',
                (sys, nut)).fetchall()
            true_labels = [r[0] for r in rows]
            pred_labels = [r[1] for r in rows]

            f1s = [compute_f1(pred_labels, true_labels, cls)
                   for cls in FSA_CLASSES]
            per_nut_f1[nut] = round(sum(f1s) / len(f1s), rd)

        macro = round(sum(per_nut_f1.values()) / len(per_nut_f1), rd)
        fsa_evaluation[sys] = {
            'macro_f1': macro,
            'per_nutrient_f1': per_nut_f1
        }

    # --- Error analysis ---
    error_analysis = {}
    for sys in systems:
        per_nutrient = {}
        ea_rows = c.execute(
            'SELECT nutrient, bias, mae, rmse, tolerance_margin '
            'FROM error_analysis_results WHERE system_name=? ORDER BY nutrient',
            (sys,)).fetchall()
        for nut, bias, mae, rmse, tol_margin in ea_rows:
            per_nutrient[nut] = {
                'bias': bias, 'mae': mae, 'rmse': rmse,
                'tolerance_margin': tol_margin
            }

        summary = c.execute(
            'SELECT overall_mae, overall_rmse, mean_tolerance_margin '
            'FROM error_analysis_summary WHERE system_name=?',
            (sys,)).fetchone()

        error_analysis[sys] = {
            'per_nutrient': per_nutrient,
            'overall_mae': summary[0] if summary else None,
            'overall_rmse': summary[1] if summary else None,
            'mean_tolerance_margin': summary[2] if summary else None
        }

    # --- Composite scores and ranking ---
    composite_scores = {}
    ranking = []
    for _, sys, score in c.execute(
            'SELECT * FROM system_ranking ORDER BY rank_order'):
        composite_scores[sys] = score
        ranking.append(sys)

    # --- Bootstrap significance ---
    bootstrap_significance = {}
    for key, pval, sig in c.execute('SELECT * FROM significance_results'):
        bootstrap_significance[key] = {
            'p_value': pval,
            'significant_at_0.05': bool(sig)
        }

    results = {
        'tolerance_accuracy': tolerance_accuracy,
        'fsa_evaluation': fsa_evaluation,
        'error_analysis': error_analysis,
        'composite_scores': composite_scores,
        'system_ranking': ranking,
        'bootstrap_significance': bootstrap_significance
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"Report written to {OUTPUT_PATH}")


if __name__ == '__main__':
    main()
