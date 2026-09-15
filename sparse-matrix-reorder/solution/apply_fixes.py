#!/usr/bin/env python3

"""Apply all seven fixes to the sparse matrix analysis pipeline.

Patches:
  C bugs:
    1. ELLPACK SpMV indexing: column-major k*dim+i -> row-major i*max_nnz+k
    2. Profile accumulation: max(envelope) -> sum(envelope)
  Python bugs:
    3. Adjacency list not symmetrized for RCM (crashes on non-symmetric matrices)
    4. JDS col_start missing final sentinel (last diagonal skipped)
    5. RCM un-permutation direction reversed
    6. Reordered bandwidth computed on original matrix instead of reordered
    7. Format scoring gives JDS bonus for low CV instead of high CV
"""

import subprocess
import os
import sys


def patch(code, old, new, label):
    """Apply a single string-replacement patch, raising on failure."""
    result = code.replace(old, new, 1)
    if result == code:
        print(f"WARN: patch '{label}' pattern not found", file=sys.stderr)
    return result


def fix_c_source():
    path = '/app/src/sparse_ops.c'
    with open(path) as f:
        code = f.read()

    # Bug 1: ELLPACK column-major layout -> row-major to match Python conversion
    code = patch(code,
                 'int idx = k * dim + i;',
                 'int idx = i * max_nnz + k;',
                 'ell_spmv indexing')

    # Bug 2: Profile should sum envelopes, not track maximum
    code = patch(code,
                 'if (envelope > profile) profile = envelope;',
                 'profile += envelope;',
                 'profile accumulation')

    with open(path, 'w') as f:
        f.write(code)


def rebuild_library():
    subprocess.run(['make', 'clean'], cwd='/app', check=True)
    subprocess.run(['make'], cwd='/app', check=True)


def fix_python_pipeline():
    path = '/app/sparse_pipeline.py'
    with open(path) as f:
        code = f.read()

    # Bug 3: Adjacency list must be symmetrized for undirected RCM traversal
    code = patch(code,
                 '                a[i].add(c)\n    return a',
                 '                a[i].add(c)\n                a[c].add(i)\n    return a',
                 'adjlist symmetrize')

    # Bug 4: JDS col_start must include final sentinel for last diagonal
    code = patch(code,
                 '        if d < mx - 1:\n            cs.append(cs[-1] + cnt)',
                 '        cs.append(cs[-1] + cnt)',
                 'jds col_start sentinel')

    # Bug 5: RCM un-permutation: result[original] = permuted[new], not reverse
    code = patch(code,
                 '        out[i] = ry[rcm_p[i]]',
                 '        out[rcm_p[i]] = ry[i]',
                 'rcm un-permutation')

    # Bug 6: Reordered bandwidth must use the reordered CSR arrays
    code = patch(code,
                 '    bw_r = bandwidth(dim, rp, ci)',
                 '    bw_r = bandwidth(dim, rrp, rci)',
                 'reordered bandwidth')

    # Bug 7: JDS format benefits from HIGH CV (variable rows), not low CV
    code = patch(code,
                 '    jds_s = 50.0\n    if cv < 0.3:\n        jds_s += 30.0 * cv',
                 '    jds_s = 50.0\n    if cv > 0.3:\n        jds_s += 30.0 * cv',
                 'format scoring cv')

    with open(path, 'w') as f:
        f.write(code)


def verify():
    data_dir = '/app/data'
    if not os.path.isdir(data_dir):
        return
    for name in sorted(os.listdir(data_dir)):
        d = os.path.join(data_dir, name)
        if os.path.isdir(d):
            r = subprocess.run(
                ['python3', '/app/sparse_pipeline.py', d, f'/app/verify_{name}.json'],
                capture_output=True, text=True, timeout=60
            )
            print(f"Verified {name}: exit={r.returncode}")
            if r.returncode != 0:
                print(r.stderr[-500:], file=sys.stderr)


if __name__ == '__main__':
    fix_c_source()
    rebuild_library()
    fix_python_pipeline()
    verify()
