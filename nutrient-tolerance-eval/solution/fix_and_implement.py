#!/usr/bin/env python3
"""Fix all defects and implement missing modules in the nutrient compliance
evaluation pipeline.

"""


def patch(path, replacements):
    with open(path) as f:
        content = f.read()
    for old, new in replacements:
        assert old in content, f"Pattern not found in {path}: {old!r}"
        content = content.replace(old, new, 1)
    with open(path, 'w') as f:
        f.write(content)
    print(f"Patched {path}")


# ================================================================
# Bug 1 — tolerance_check.py
# Relative tolerance incorrectly uses predicted value as reference;
# EU 1169/2011 requires computing tolerance relative to the actual value.
# ================================================================
patch('/app/src/tolerance_check.py', [
    ('abs(predicted - actual) <= predicted * tol_value',
     'abs(predicted - actual) <= actual * tol_value'),
])

# ================================================================
# Bug 2 — fsa_labeler.py
# Low threshold uses strict < instead of <=; FSA rules specify that
# values at or below the low threshold are classified as green.
# ================================================================
patch('/app/src/fsa_labeler.py', [
    ('if value < low:',
     'if value <= low:'),
])

# ================================================================
# Bug 3 — scoring.py
# Composite weight config keys are swapped: reads 'fsa' for tolerance
# weight and 'tolerance' for fsa weight.
# ================================================================
patch('/app/src/scoring.py', [
    ("tolerance_weight = weights['fsa']",
     "tolerance_weight = weights['tolerance']"),
    ("fsa_weight = weights['tolerance']",
     "fsa_weight = weights['fsa']"),
])

# ================================================================
# Bug 4 — significance.py
# Paired bootstrap missing shift-method centering: raw differences are
# resampled instead of zero-centered differences.
# ================================================================
patch('/app/src/significance.py', [
    ('        n = len(diffs)\n'
     '        count_extreme = 0\n'
     '        for _ in range(n_resamples):\n'
     '            sample = [diffs[rng.randint(0, n - 1)] for _ in range(n)]',

     '        centered = [d - observed_mean for d in diffs]\n'
     '        n = len(centered)\n'
     '        count_extreme = 0\n'
     '        for _ in range(n_resamples):\n'
     '            sample = [centered[rng.randint(0, n - 1)] for _ in range(n)]'),
])

# ================================================================
# Bug 5 — report.py
# Per-nutrient tolerance accuracy SQL query is missing GROUP BY nutrient,
# so every nutrient gets the same overall accuracy value.
# ================================================================
patch('/app/src/report.py', [
    ("        row = c.execute(\n"
     "            'SELECT CAST(SUM(within_tolerance) AS REAL) / COUNT(*) '\n"
     "            'FROM tolerance_results WHERE system_name=?',\n"
     "            (sys,)).fetchone()\n"
     "        for nut in NUTRIENTS:\n"
     "            per_nutrient[nut] = round(row[0], rd)",

     "        rows = c.execute(\n"
     "            'SELECT nutrient, CAST(SUM(within_tolerance) AS REAL) / COUNT(*) '\n"
     "            'FROM tolerance_results WHERE system_name=? '\n"
     "            'GROUP BY nutrient ORDER BY nutrient',\n"
     "            (sys,)).fetchall()\n"
     "        for nut_name, acc in rows:\n"
     "            per_nutrient[nut_name] = round(acc, rd)"),
])

# ================================================================
# Fix 6 — Makefile
# The error_analysis target exists but results.json does not depend
# on .error_analysis_done, so error analysis never runs.
# ================================================================
patch('/app/Makefile', [
    ('/app/output/results.json: /app/.significance_done /app/src/report.py',
     '/app/output/results.json: /app/.significance_done /app/.error_analysis_done /app/src/report.py'),
])

# ================================================================
# Fix 7 — Implement error_analysis.py from specification
# ================================================================
ERROR_ANALYSIS_CODE = '''\
#!/usr/bin/env python3
"""Compute prediction error statistics for each system and nutrient.

Implements the specification from /app/docs/error_analysis_spec.md.
"""
import json
import math
import sqlite3

DB_PATH = '/app/pipeline.db'
NUTRIENTS = ['energy', 'fat', 'saturates', 'sugars', 'protein', 'salt']


def get_tolerance_bound(actual, tiers):
    """Compute the tolerance bound for a given actual value.

    Parameters
    ----------
    actual : float  – ground-truth (declared) value
    tiers  : list of (max_actual, tolerance_type, tolerance_value) tuples
    """
    for max_actual, tol_type, tol_value in tiers:
        if max_actual is None or actual <= max_actual:
            if tol_type == 'absolute':
                return tol_value
            else:
                if actual == 0:
                    return 1e-9
                return abs(actual) * tol_value
    return 0.0


def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    rd = int(c.execute(
        "SELECT value FROM config WHERE key=\'round_digits\'").fetchone()[0])

    # Load tolerance rules
    nutrient_list = [r[0] for r in c.execute(
        'SELECT DISTINCT nutrient FROM tolerance_rules ORDER BY nutrient')]
    rules = {}
    for nut in nutrient_list:
        rules[nut] = c.execute(
            'SELECT max_actual, tolerance_type, tolerance_value '
            'FROM tolerance_rules WHERE nutrient=? ORDER BY tier_order',
            (nut,)).fetchall()

    systems = [r[0] for r in c.execute(
        'SELECT DISTINCT system_name FROM predictions ORDER BY system_name')]

    c.execute('DELETE FROM error_analysis_results')
    c.execute('DELETE FROM error_analysis_summary')

    for sys in systems:
        per_nutrient_mae = {}
        per_nutrient_rmse = {}
        per_nutrient_margin = {}

        for nut in NUTRIENTS:
            rows = c.execute(
                'SELECT p.predicted_value, r.actual_value '
                'FROM predictions p JOIN recipes r '
                'ON p.recipe_id=r.recipe_id AND p.nutrient=r.nutrient '
                'WHERE p.system_name=? AND p.nutrient=? ORDER BY p.recipe_id',
                (sys, nut)).fetchall()

            errors = []
            abs_errors = []
            sq_errors = []
            margins = []

            for pred, actual in rows:
                err = pred - actual
                abs_err = abs(err)
                errors.append(err)
                abs_errors.append(abs_err)
                sq_errors.append(err ** 2)

                bound = get_tolerance_bound(actual, rules[nut])
                margin = (bound - abs_err) / bound if bound > 0 else 0.0
                margins.append(margin)

            n = len(errors)
            bias = round(sum(errors) / n, rd)
            mae = round(sum(abs_errors) / n, rd)
            rmse = round(math.sqrt(sum(sq_errors) / n), rd)
            tol_margin = round(sum(margins) / n, rd)

            per_nutrient_mae[nut] = mae
            per_nutrient_rmse[nut] = rmse
            per_nutrient_margin[nut] = tol_margin

            c.execute('INSERT INTO error_analysis_results VALUES (?,?,?,?,?,?)',
                      (sys, nut, bias, mae, rmse, tol_margin))

        overall_mae = round(
            sum(per_nutrient_mae.values()) / len(per_nutrient_mae), rd)
        overall_rmse = round(
            sum(per_nutrient_rmse.values()) / len(per_nutrient_rmse), rd)
        mean_tol_margin = round(
            sum(per_nutrient_margin.values()) / len(per_nutrient_margin), rd)

        c.execute('INSERT INTO error_analysis_summary VALUES (?,?,?,?)',
                  (sys, overall_mae, overall_rmse, mean_tol_margin))

    conn.commit()
    conn.close()
    print("Error analysis complete.")


if __name__ == \'__main__\':
    main()
'''

with open('/app/src/error_analysis.py', 'w') as f:
    f.write(ERROR_ANALYSIS_CODE)
print("Wrote /app/src/error_analysis.py")

print("All pipeline defects patched and missing module implemented.")
