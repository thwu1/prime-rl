#!/usr/bin/env python3
"""Compute EU 1169/2011 tolerance compliance for each prediction system."""
import sqlite3

DB_PATH = '/app/pipeline.db'


def check_tolerance(predicted, actual, tiers):
    """Check if a predicted nutrient value falls within the regulatory
    tolerance band of the actual (declared) value.

    Parameters
    ----------
    predicted : float  – system's predicted value
    actual    : float  – ground-truth (declared) value
    tiers     : list of (max_actual, tolerance_type, tolerance_value) tuples
    """
    for max_actual, tol_type, tol_value in tiers:
        if max_actual is None or actual <= max_actual:
            if tol_type == 'absolute':
                return abs(predicted - actual) <= tol_value
            else:
                if actual == 0:
                    return abs(predicted) <= 1e-9
                return abs(predicted - actual) <= predicted * tol_value
    return False


def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    nutrients = [r[0] for r in c.execute(
        'SELECT DISTINCT nutrient FROM tolerance_rules ORDER BY nutrient')]
    rules = {}
    for nut in nutrients:
        rules[nut] = c.execute(
            'SELECT max_actual, tolerance_type, tolerance_value '
            'FROM tolerance_rules WHERE nutrient=? ORDER BY tier_order',
            (nut,)).fetchall()

    systems = [r[0] for r in c.execute(
        'SELECT DISTINCT system_name FROM predictions ORDER BY system_name')]

    c.execute('DELETE FROM tolerance_results')

    for sys in systems:
        rows = c.execute(
            'SELECT p.recipe_id, p.nutrient, p.predicted_value, r.actual_value '
            'FROM predictions p JOIN recipes r '
            'ON p.recipe_id=r.recipe_id AND p.nutrient=r.nutrient '
            'WHERE p.system_name=? ORDER BY p.recipe_id, p.nutrient',
            (sys,)).fetchall()

        for rid, nut, pred_val, actual_val in rows:
            within = 1 if check_tolerance(pred_val, actual_val, rules[nut]) else 0
            c.execute('INSERT INTO tolerance_results VALUES (?,?,?,?)',
                      (sys, rid, nut, within))

    conn.commit()
    conn.close()
    print("Tolerance checking complete.")


if __name__ == '__main__':
    main()
