#!/usr/bin/env python3
"""Fix all defects in the nutrient compliance evaluation pipeline.

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


# Bug 1 — tolerance_check.py
# Relative tolerance incorrectly uses predicted value as reference;
# EU 1169/2011 requires computing tolerance relative to the actual value.
patch('/app/src/tolerance_check.py', [
    ('abs(predicted - actual) <= predicted * tol_value',
     'abs(predicted - actual) <= actual * tol_value'),
])

# Bug 2 — fsa_labeler.py
# Low threshold uses strict < instead of <=; FSA rules specify that
# values at or below the low threshold are classified as green.
patch('/app/src/fsa_labeler.py', [
    ('if value < low:',
     'if value <= low:'),
])

# Bug 3 — scoring.py
# Composite weight config keys are swapped: reads 'fsa' for tolerance
# weight and 'tolerance' for fsa weight.
patch('/app/src/scoring.py', [
    ("tolerance_weight = weights['fsa']",
     "tolerance_weight = weights['tolerance']"),
    ("fsa_weight = weights['tolerance']",
     "fsa_weight = weights['fsa']"),
])

# Bug 4 — significance.py
# Paired bootstrap missing shift-method centering: raw differences are
# resampled instead of zero-centered differences.
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

# Bug 5 — report.py
# Per-nutrient tolerance accuracy SQL query is missing GROUP BY nutrient,
# so every nutrient gets the same overall accuracy value.
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

print("All pipeline defects patched.")
