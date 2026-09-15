#!/usr/bin/env python3
"""Fix all bugs in the FuzzBench multi-tool analysis pipeline.

Patches the 5 bugs across 4 tools and prepares for re-run.

"""

# Bug 1 (SQL): MIN(time) -> MAX(time) to get final coverage snapshot
with open('/app/pipeline/extract_data.sql') as f:
    sql_code = f.read()
sql_code = sql_code.replace('MIN(time)', 'MAX(time)')
with open('/app/pipeline/extract_data.sql', 'w') as f:
    f.write(sql_code)
print("Fixed SQL: MIN(time) -> MAX(time)")

# Bug 2 (R): rank direction ascending -> descending (rank 1 = best)
with open('/app/pipeline/statistical_tests.R') as f:
    r_code = f.read()
r_code = r_code.replace(
    't(apply(med_matrix, 1, rank))',
    't(apply(med_matrix, 1, function(x) rank(-x)))'
)

# Bug 3 (R): SE denominator k -> n_bench
r_code = r_code.replace(
    'sqrt(k * (k + 1) / (12.0 * k))',
    'sqrt(k * (k + 1) / (12.0 * n_bench))'
)
with open('/app/pipeline/statistical_tests.R', 'w') as f:
    f.write(r_code)
print("Fixed R: rank direction and SE denominator")

# Bug 4 (Python): A12 missing tie handling
with open('/app/pipeline/compute_metrics.py') as f:
    py_code = f.read()
py_code = py_code.replace(
    '            if xi > yj:\n                r += 1.0',
    '            if xi > yj:\n                r += 1.0\n            elif xi == yj:\n                r += 0.5'
)
with open('/app/pipeline/compute_metrics.py', 'w') as f:
    f.write(py_code)
print("Fixed Python: A12 tie handling")

# Bug 5 (jq): remove 'reverse' from ranking sort
with open('/app/pipeline/merge_results.jq') as f:
    jq_code = f.read()
jq_code = jq_code.replace(' | reverse', '')
with open('/app/pipeline/merge_results.jq', 'w') as f:
    f.write(jq_code)
print("Fixed jq: removed reverse from ranking")

print("\nAll 5 pipeline bugs fixed. Re-run the pipeline to generate corrected results.")
