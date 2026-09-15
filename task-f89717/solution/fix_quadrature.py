#!/usr/bin/env python3
"""
Fix the four bugs in /app/quadrature.py:

1. Transposed Kronrod weights at indices 2 and 4 in the _WGK array.
2. Min-heap instead of max-heap in adaptive subdivision (errors stored
   as positive values, so heapq pops the *smallest* error first instead
   of the largest).
3. Wrong row index in Wynn epsilon algorithm recurrence: uses e[i][k-2]
   instead of the correct e[i+1][k-2].
4. Missing square in the semi-infinite interval Jacobian: uses 1/(1-t)
   instead of the correct 1/(1-t)^2.
"""


path = '/app/quadrature.py'

with open(path) as f:
    lines = f.readlines()

out = []
for line in lines:
    # --- Bug 1: fix transposed Kronrod weights ---
    if '0.16900472663926790,  # 2' in line:
        line = line.replace('0.16900472663926790', '0.10479001032225019')
    elif '0.10479001032225019,  # 4' in line:
        line = line.replace('0.10479001032225019', '0.16900472663926790')

    # --- Bug 2: negate errors for max-heap behaviour ---
    elif 'heap = [(err,' in line:
        line = line.replace('(err,', '(-err,')
    elif 'heapq.heappush(heap, (e1,' in line:
        line = line.replace('(e1,', '(-e1,')
    elif 'heapq.heappush(heap, (e2,' in line:
        line = line.replace('(e2,', '(-e2,')
    elif 'old_err, _, ia, ib, old_res = heapq.heappop(heap)' in line:
        indent = line[:len(line) - len(line.lstrip())]
        out.append(f'{indent}neg_old_err, _, ia, ib, old_res = heapq.heappop(heap)\n')
        out.append(f'{indent}old_err = -neg_old_err\n')
        continue

    # --- Bug 3: fix epsilon recurrence row index ---
    if 'e[i][k - 2] + 1.0 / delta' in line:
        line = line.replace('e[i][k - 2]', 'e[i + 1][k - 2]')

    # --- Bug 4: fix Jacobian for semi-infinite transform ---
    if 'jac = 1.0 / omt' in line and 'omt *' not in line:
        line = line.replace('1.0 / omt', '1.0 / (omt * omt)')

    out.append(line)

with open(path, 'w') as f:
    f.writelines(out)

print('All four bugs fixed in quadrature.py')
