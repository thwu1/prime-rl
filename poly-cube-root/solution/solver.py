#!/usr/bin/env python3
"""
Oracle solution: compute the polynomial cube root g(x) where g(x)^3 = f(x)
over Z/998244353Z using Newton iteration with NTT-based polynomial arithmetic.

Uses the compiled C++ polytool binary at /app/bin/polytool for O(N log N)
polynomial multiplication and inverse, avoiding fragile database parsing.
"""

import struct
import os
import subprocess

P = 998244353
INV3 = pow(3, P - 2, P)  # modular inverse of 3
N = 65536
POLYTOOL = '/app/bin/polytool'
TMPDIR = '/tmp/poly_work'
os.makedirs(TMPDIR, exist_ok=True)


def read_poly_bin(path):
    """Read a binary .poly file."""
    with open(path, 'rb') as fp:
        magic = fp.read(4)
        assert magic == b'POLY', f"Bad magic in {path}: {magic!r}"
        prime, count = struct.unpack('<II', fp.read(8))
        coeffs = list(struct.unpack(f'<{count}I', fp.read(4 * count)))
    return prime, coeffs


def write_poly_bin(path, prime, coeffs):
    """Write a binary .poly file."""
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, 'wb') as fp:
        fp.write(b'POLY')
        fp.write(struct.pack('<II', prime, len(coeffs)))
        fp.write(struct.pack(f'<{len(coeffs)}I', *coeffs))


def polytool_run(*args):
    """Run the polytool binary with given arguments."""
    cmd = [POLYTOOL] + [str(a) for a in args]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"polytool {' '.join(str(a) for a in args)}: {r.stderr}")


def poly_mul_naive(a, b, trunc):
    """Naive O(N^2) polynomial multiplication -- only for small checkpoint verification."""
    result = [0] * trunc
    for i in range(min(len(a), trunc)):
        for j in range(min(len(b), trunc - i)):
            result[i + j] = (result[i + j] + a[i] * b[j]) % P
    return result


# ---- Step 1: Read input polynomial f ----
f_path = '/app/workspace/data/f_input.poly'
_, f_coeffs = read_poly_bin(f_path)
print(f"Loaded f: {len(f_coeffs)} coefficients, f[0]={f_coeffs[0]}")

# ---- Step 2: Verify checkpoints to find last known-good iterate ----
# Directly verify g^3 = f mod x^prec for each stored iterate.
# This is independent of any database queries.
best_g = [1]  # fallback: g_0 = 1 (cube root of f(0) = 1)
best_prec = 1

for cp_name in ['g_iter0', 'g_iter1', 'g_iter2']:
    cp_path = f'/app/workspace/data/{cp_name}.poly'
    if not os.path.exists(cp_path):
        print(f"  {cp_name}: not found")
        continue
    _, gc = read_poly_bin(cp_path)
    prec = len(gc)
    # Verify: g^3 should equal f mod x^prec (small sizes: at most 4 terms)
    g_sq = poly_mul_naive(gc, gc, prec)
    g_cubed = poly_mul_naive(g_sq, gc, prec)
    valid = all(g_cubed[i] == f_coeffs[i] for i in range(prec))
    if valid and prec > best_prec:
        best_g, best_prec = gc, prec
        print(f"  {cp_name}: PASS (precision {prec})")
    elif not valid:
        print(f"  {cp_name}: CORRUPTED")
    else:
        print(f"  {cp_name}: valid but not better than current best")

print(f"Starting Newton iteration from precision {best_prec}")

# ---- Step 3: Newton iteration using polytool for NTT operations ----
# Recurrence: g_{k+1} = (2*g_k + f * inv(g_k^2)) * 3^{-1}  mod x^{2M}
g = list(best_g)
cur_prec = best_prec

step = 0
while cur_prec < N:
    cur_prec = min(cur_prec * 2, N)
    step += 1
    print(f"Newton step {step}: precision -> {cur_prec}", flush=True)

    # Pad g to cur_prec terms
    gp = g + [0] * (cur_prec - len(g))

    # Write current g to temp file
    g_cur_path = f'{TMPDIR}/g_cur.poly'
    write_poly_bin(g_cur_path, P, gp)

    # Write truncated f (only first cur_prec terms needed for mod x^M)
    f_trunc_path = f'{TMPDIR}/f_trunc.poly'
    write_poly_bin(f_trunc_path, P, f_coeffs[:cur_prec])

    # Compute g^2 mod x^M using polytool NTT
    g_sq_path = f'{TMPDIR}/g_sq.poly'
    polytool_run('mul', g_cur_path, g_cur_path, '-o', g_sq_path, '-n', cur_prec)

    # Compute (g^2)^{-1} mod x^M using polytool Newton inverse
    g_sq_inv_path = f'{TMPDIR}/g_sq_inv.poly'
    polytool_run('inv', g_sq_path, '-o', g_sq_inv_path, '-n', cur_prec)

    # Compute f * (g^2)^{-1} mod x^M
    fg_path = f'{TMPDIR}/fg.poly'
    polytool_run('mul', f_trunc_path, g_sq_inv_path, '-o', fg_path, '-n', cur_prec)

    # Read fg result
    _, fg_coeffs = read_poly_bin(fg_path)

    # Combine: g_new = (2*g + f*(g^2)^{-1}) * 3^{-1} mod P
    g = [(2 * gp[i] + fg_coeffs[i]) % P * INV3 % P for i in range(cur_prec)]

# ---- Step 4: Write output ----
out_path = '/app/workspace/output/g_final.poly'
write_poly_bin(out_path, P, g)
print(f"Done. Wrote {len(g)} coefficients to {out_path}")
