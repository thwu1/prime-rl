#!/usr/bin/env python3
"""Set up the workspace for the interrupted computation task.

Creates: SQLite project database, binary polynomial files, algorithm notes,
run logs, and corrupted checkpoint. The workspace simulates a researcher's
interrupted Newton-based polynomial cube root computation over Z/998244353Z,
with data integrity issues requiring forensic diagnosis.
"""
import os
import random
import sqlite3
import struct

random.seed(42)
N = 65536
P = 998244353
G = 3  # primitive root of P


def ntt(a, invert=False):
    n = len(a)
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        if i < j:
            a[i], a[j] = a[j], a[i]
    ln = 2
    while ln <= n:
        if invert:
            w = pow(G, P - 1 - (P - 1) // ln, P)
        else:
            w = pow(G, (P - 1) // ln, P)
        half = ln >> 1
        for i in range(0, n, ln):
            wn = 1
            for k in range(half):
                u = a[i + k]
                v = a[i + k + half] * wn % P
                a[i + k] = (u + v) % P
                a[i + k + half] = (u - v) % P
                wn = wn * w % P
        ln <<= 1
    if invert:
        inv_n = pow(n, P - 2, P)
        for i in range(n):
            a[i] = a[i] * inv_n % P


def poly_mul(a, b, trunc=None):
    la, lb = len(a), len(b)
    rl = la + lb - 1
    if trunc is None:
        trunc = rl
    n = 1
    while n < la + lb:
        n <<= 1
    fa = list(a) + [0] * (n - la)
    fb = list(b) + [0] * (n - lb)
    ntt(fa)
    ntt(fb)
    for i in range(n):
        fa[i] = fa[i] * fb[i] % P
    ntt(fa, True)
    result = [0] * trunc
    for i in range(min(rl, trunc)):
        result[i] = fa[i]
    return result


def poly_inv(f_in, m):
    h = [pow(f_in[0], P - 2, P)]
    cur = 1
    while cur < m:
        cur <<= 1
        fl = min(len(f_in), cur)
        ft = list(f_in[:fl]) + [0] * (cur - fl)
        fh = poly_mul(ft, h, cur)
        neg_fh = [(P - fh[i]) % P for i in range(cur)]
        neg_fh[0] = (neg_fh[0] + 2) % P
        h = poly_mul(h, neg_fh, cur)
    return h[:m]


def cbrt_step(f_in, g_prev, new_prec):
    inv3 = pow(3, P - 2, P)
    gp = list(g_prev) + [0] * (new_prec - len(g_prev))
    fl = min(len(f_in), new_prec)
    ft = list(f_in[:fl]) + [0] * (new_prec - fl)
    g_sq = poly_mul(gp, gp, new_prec)
    g_sq_inv = poly_inv(g_sq, new_prec)
    fg = poly_mul(ft, g_sq_inv, new_prec)
    return [(2 * gp[i] + fg[i]) % P * inv3 % P for i in range(new_prec)]


def write_poly_bin(path, prime, coeffs):
    with open(path, 'wb') as fp:
        fp.write(b'POLY')
        fp.write(struct.pack('<II', prime, len(coeffs)))
        fp.write(struct.pack(f'<{len(coeffs)}I', *coeffs))


# Generate the true cube root polynomial g_orig
D = N // 3 + 1  # 21846 coefficients
g_orig = [1] + [random.randint(1, P - 1) for _ in range(D - 1)]

# Compute f = g_orig^3
print("Computing f = g_orig^3 ...")
g_sq = poly_mul(g_orig, g_orig)
f = poly_mul(g_sq, g_orig)
assert len(f) == N, f"Expected {N} coefficients, got {len(f)}"
assert f[0] == 1, f"f(0) should be 1, got {f[0]}"

# Compute Newton iterates (small precision, fast)
print("Computing Newton iterates ...")
g0 = [1]
g1 = cbrt_step(f, g0, 2)
g2 = cbrt_step(f, g1, 4)

# Verify iterates
g1_cubed = poly_mul(poly_mul(g1, g1, 2), g1, 2)
for i in range(2):
    assert g1_cubed[i] == f[i], f"g1 verify failed at {i}"
g2_cubed = poly_mul(poly_mul(g2, g2, 4), g2, 4)
for i in range(4):
    assert g2_cubed[i] == f[i], f"g2 verify failed at {i}"
print("Newton iterates verified.")

# Create directories
os.makedirs('/app/workspace/data', exist_ok=True)
os.makedirs('/app/workspace/output', exist_ok=True)
os.makedirs('/app/workspace/notes', exist_ok=True)
os.makedirs('/app/workspace/logs', exist_ok=True)
os.makedirs('/app/bin', exist_ok=True)

# Write binary polynomial files
print("Writing polynomial data files ...")
write_poly_bin('/app/workspace/data/f_input.poly', P, f)
write_poly_bin('/app/workspace/data/g_iter0.poly', P, g0)
write_poly_bin('/app/workspace/data/g_iter1.poly', P, g1)

# Write CORRUPTED g_iter2 — flip coefficient at index 2
g2_corrupt = list(g2)
g2_corrupt[2] = (g2_corrupt[2] + 738291) % P
write_poly_bin('/app/workspace/data/g_iter2.poly', P, g2_corrupt)
print(f"g_iter2 corrupted: coeff[2] changed from {g2[2]} to {g2_corrupt[2]}")

# Create SQLite database
print("Creating project database ...")
db = sqlite3.connect('/app/workspace/project.db')
c = db.cursor()

c.execute('''CREATE TABLE polynomials (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    file_path TEXT NOT NULL,
    coeff_count INTEGER NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)''')

c.execute('''CREATE TABLE journal (
    id INTEGER PRIMARY KEY,
    step_name TEXT NOT NULL,
    operation TEXT NOT NULL,
    description TEXT,
    input_poly_ids TEXT,
    output_poly_id INTEGER REFERENCES polynomials(id),
    parameters TEXT,
    status TEXT NOT NULL CHECK(status IN ('completed','pending','failed')),
    error_msg TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)''')

# Polynomials
c.execute("INSERT INTO polynomials VALUES (1,'f','Target polynomial f(x) with f(0)=1','/app/workspace/data/f_input.poly',?,datetime('now'))", (N,))
c.execute("INSERT INTO polynomials VALUES (2,'g_iter0','Newton iterate k=0 (precision 1)','/app/workspace/data/g_iter0.poly',1,datetime('now'))")
c.execute("INSERT INTO polynomials VALUES (3,'g_iter1','Newton iterate k=1 (precision 2)','/app/workspace/data/g_iter1.poly',2,datetime('now'))")
c.execute("INSERT INTO polynomials VALUES (4,'g_iter2','Newton iterate k=2 (precision 4)','/app/workspace/data/g_iter2.poly',4,datetime('now'))")
c.execute("INSERT INTO polynomials VALUES (5,'g_final','Final cube root result (target precision)','/app/workspace/output/g_final.poly',?,datetime('now'))", (N,))

# Journal entries — tell the forensic story
c.execute("""INSERT INTO journal VALUES (1,'load_input','file_load',
    'Load target polynomial f: 65536 coefficients modulo prime 998244353',
    NULL,1,'{"N":65536,"prime":998244353}','completed',NULL,datetime('now'))""")

c.execute("""INSERT INTO journal VALUES (2,'newton_init','cbrt_init',
    'Compute g_0 = f(0)^((2p-1)/3) mod p as the initial cube root seed',
    '[1]',2,'{"precision":1}','completed',NULL,datetime('now'))""")

c.execute("""INSERT INTO journal VALUES (3,'newton_step_1','cbrt_refine',
    'Newton refinement step: double precision from 1 to 2',
    '[1,2]',3,'{"from_precision":1,"to_precision":2}','completed',NULL,datetime('now'))""")

c.execute("""INSERT INTO journal VALUES (4,'newton_step_2','cbrt_refine',
    'Newton refinement step: double precision from 2 to 4',
    '[1,3]',4,'{"from_precision":2,"to_precision":4}','completed',NULL,datetime('now'))""")

c.execute("""INSERT INTO journal VALUES (5,'checkpoint_verify','integrity_check',
    'Post-hoc verification of all stored Newton iterates against f. For each iterate g_k of precision M, checks g_k(x)^3 == f(x) mod x^M.',
    '[1,2,3,4]',NULL,'{"method":"g^3_mod_x^prec_vs_f_mod_x^prec"}','failed',
    'Verification results:\\n  g_iter0: PASS (g[0]^3 == f[0] mod p)\\n  g_iter1: PASS (g^3 == f mod x^2, all 2 coefficients match)\\n  g_iter2: FAIL at coeff index 2 (g^3 mod x^4 != f mod x^4)\\nDiagnosis: data/g_iter2.poly appears corrupted. An fsync failure was logged around the time step 4 completed. The on-disk file does not match the expected computation output. Iterates g_iter0 and g_iter1 are intact and verified.',
    datetime('now'))""")

c.execute("""INSERT INTO journal VALUES (6,'run_attempt_1','cbrt_iterate_to_target',
    'First attempt to continue Newton iteration to target precision 65536',
    '[1,4]',5,'{"from_precision":4,"to_precision":65536,"method":"naive_poly_mul"}','failed',
    'Started from g_iter2 (now known to be corrupted -- see step 5). Used naive O(N^2) coefficient multiplication. Process killed (OOM, signal 9) at precision 8192 after running for 2+ hours. Even without corruption, this approach cannot scale to N=65536. See logs/run_attempt_001.log for full output.',
    datetime('now'))""")

c.execute("""INSERT INTO journal VALUES (7,'newton_continue','cbrt_iterate_to_target',
    'Resume cube root computation to target precision 65536. Must start from a VERIFIED iterate (see step 5). Requires NTT-based O(N log N) polynomial multiplication.',
    '[1]',5,'{"target_precision":65536,"algorithm":"newton_cbrt","notes_ref":"notes/algorithm.md"}','pending',
    'Previous attempts failed: (1) corrupted starting checkpoint, (2) O(N^2) multiplication caused OOM. Next attempt must use verified checkpoint AND efficient NTT-based arithmetic.',
    datetime('now'))""")

db.commit()
db.close()

# Write algorithm notes
print("Writing algorithm notes ...")
with open('/app/workspace/notes/algorithm.md', 'w') as fout:
    fout.write(r"""# Formal Power Series: Cube Root via Newton's Method

## Problem Statement

Given a formal power series f(x) with N coefficients over Z_p (p prime),
where f(0) is a non-zero cube in Z_p and gcd(3, p-1) = 1,
find g(x) such that:

    g(x)^3 = f(x)  mod x^N

## Newton Iteration

Define Phi(g) = g^3 - f. We seek the root Phi(g) = 0 mod x^N.

Newton's update rule for formal power series:

    g_{k+1} = g_k - Phi(g_k) / Phi'(g_k)  mod x^{2^{k+1}}

Since Phi'(g) = 3 g^2, the update simplifies to:

    g_{k+1} = (2 g_k + f * (g_k^2)^{-1}) * 3^{-1}  mod x^{2^{k+1}}

where 3^{-1} denotes the modular inverse of 3 in Z_p,
and (g_k^2)^{-1} is the formal power series inverse of g_k^2.

## Initialization

    g_0 = f(0) ^ ((2p - 1) / 3)  mod p

This is the unique cube root of f(0) in Z_p when gcd(3, p-1) = 1.

For our prime p = 998244353:
  p - 1 = 998244352 = 2^23 * 7 * 17
  gcd(3, p-1) = 1 (since 3 does not divide 2^23 * 7 * 17)
  So the cube root is unique in Z_p.

## Polynomial Inverse (subroutine)

To compute h = a^{-1} mod x^M where a(0) != 0:

    h_0 = a(0)^{-1}  mod p
    h_{j+1} = h_j * (2 - a * h_j)  mod x^{2^{j+1}}

Each doubling step requires two polynomial multiplications at the current
precision — use NTT-based O(M log M) multiplication.

## Convergence

Each Newton step doubles the number of correct coefficients.
Starting from g_0 (1 correct coefficient), after ceil(log2(N)) steps
we obtain g correct to N coefficients.

## Complexity

Each cube root Newton step at precision M requires:
  - 1 polynomial squaring (M terms)
  - 1 polynomial inverse (M terms, itself O(log M) Newton sub-steps)
  - 1 polynomial multiplication (M terms)
  - 1 scalar multiply + addition

With NTT-based multiplication in O(M log M), each step costs O(M log^2 M).
Total across all doubling steps: O(N log^2 N).

Naive O(M^2) multiplication is feasible only up to M ~ 4096.

## NTT Prerequisites

For NTT to work over Z_p, the prime p must satisfy:
  - p = c * 2^k + 1 for sufficiently large k (so that we have enough roots of unity)
  - We need a primitive root g of Z_p (generator of the multiplicative group)

For p = 998244353 = 119 * 2^23 + 1:
  - Maximum NTT size: 2^23 = 8388608 (far exceeds our needs)
  - Primitive root: 3
""")

# Write alternative approaches notes
with open('/app/workspace/notes/alternative_approaches.md', 'w') as fout:
    fout.write(r"""# Alternative Approaches for Polynomial Roots

## Method A: Direct Newton Iteration

The standard approach — see algorithm.md.
Uses the recurrence g_{k+1} = (2g_k + f * inv(g_k^2)) / 3.
Requires: NTT-based poly multiplication + Newton-based poly inverse.

## Method B: Formal Power Series Logarithm and Exponential

If f(0) = 1, we can compute:

    g(x) = f(x)^{1/3} = exp( log(f(x)) / 3 )  mod x^N

This decomposes the problem into:
  1. log(f) mod x^N  — via integration of f'(x) / f(x)
  2. scalar division by 3
  3. exp of the result

Implementing poly_log requires:
  - Formal derivative: f'(x) = sum_{i>=1} i * a_i * x^{i-1}
  - Polynomial inverse: 1/f(x) mod x^N  (Newton iteration)
  - Polynomial multiplication of f' * (1/f)
  - Formal integration: int h(x) = sum_{i>=0} h_i/(i+1) * x^{i+1}
    Note: division by (i+1) requires computing modular inverses of 1..N

Implementing poly_exp requires:
  - Newton iteration: if E = exp(h), then E_{k+1} = E_k * (1 + h - log(E_k))
  - This needs poly_log inside poly_exp, making it more complex

Advantages: conceptually clean decomposition
Disadvantages:
  - Requires implementing BOTH poly_log and poly_exp
  - poly_exp internally calls poly_log at each Newton step
  - Roughly 3x the constant factor compared to direct Newton cube root
  - More subroutines = more opportunities for bugs
  - Needs precomputed modular inverses of 1..N

## Method C: Coefficient-by-Coefficient (Hensel Lifting)

Compute g one coefficient at a time:
  Given g_0, ..., g_{k-1}, determine g_k from the equation
  [x^k] g(x)^3 = [x^k] f(x)

This gives a linear equation in g_k (since g_0 = 1):
  3 * g_0^2 * g_k = f_k - (contributions from g_0..g_{k-1})

Time complexity: O(N^2) — each coefficient requires summing over all
prior coefficients. Not viable for N > ~4096 on current hardware.

## Recommendation

Method A (direct Newton) is the most practical for large N. It requires
the fewest subroutines (NTT + poly_inv) and has the smallest constant
factor. Method B is mathematically elegant but implementation-heavy.
Method C is simple but quadratically slow.
""")

# Write crash log from failed run attempt
with open('/app/workspace/logs/run_attempt_001.log', 'w') as fout:
    fout.write("""=== Cube Root Computation — Run Attempt #1 ===
Date: 2024-03-15 14:23:07
Method: naive coefficient-by-coefficient polynomial multiplication
Starting checkpoint: g_iter2 (precision 4, from data/g_iter2.poly)
Target: precision 65536

[14:23:07] Loading f_input.poly: 65536 coefficients mod 998244353
[14:23:07] Loading g_iter2.poly: 4 coefficients
[14:23:07] Beginning Newton iteration (14 doubling steps planned)
[14:23:07] Step  1/14: precision    4 ->    8 ... done (0.01s, poly_mul 2x at N=8)
[14:23:07] Step  2/14: precision    8 ->   16 ... done (0.03s, poly_mul 2x at N=16)
[14:23:08] Step  3/14: precision   16 ->   32 ... done (0.11s, poly_mul 2x at N=32)
[14:23:08] Step  4/14: precision   32 ->   64 ... done (0.44s, poly_mul 2x at N=64)
[14:23:09] Step  5/14: precision   64 ->  128 ... done (1.8s, poly_mul 2x at N=128)
[14:23:11] Step  6/14: precision  128 ->  256 ... done (7.1s, poly_mul 2x at N=256)
[14:23:19] Step  7/14: precision  256 ->  512 ... done (28.6s, poly_mul 2x at N=512)
[14:23:48] Step  8/14: precision  512 -> 1024 ... done (114s, poly_mul 2x at N=1024)
[14:25:42] Step  9/14: precision 1024 -> 2048 ... done (458s, poly_mul 2x at N=2048)
[14:33:20] Step 10/14: precision 2048 -> 4096 ... done (1842s, poly_mul 2x at N=4096)
[15:04:02] Step 11/14: precision 4096 -> 8192 ...
[15:04:02] WARNING: O(N^2) poly_mul at N=8192: estimated 67M multiply-add operations
[15:04:02] WARNING: estimated wall time for this step: ~2 hours
[15:04:02] WARNING: estimated memory for intermediate arrays: ~1.2 GB

[16:27:35] Process terminated: signal 9 (SIGKILL)
[16:27:35] Likely cause: Out of Memory (system OOM killer)

=== Post-mortem ===
Root cause: O(N^2) polynomial multiplication is infeasible beyond N ~ 4096.
Scaling: each doubling of N quadruples the time and memory.
At N=8192: ~67M operations, ~1.2 GB intermediate arrays.
At N=65536: ~4.3B operations, ~78 GB — completely infeasible.

Recommendation: implement NTT-based polynomial multiplication.
P = 998244353 = 119 * 2^23 + 1 is NTT-friendly; primitive root = 3.
NTT reduces O(N^2) multiplication to O(N log N).

NOTE: This run used g_iter2 as starting checkpoint. Subsequent integrity
check (journal step 5) found g_iter2 to be CORRUPTED. Even if this run
had completed, the output would have been incorrect.
""")

# Write workspace README
with open('/app/workspace/README.txt', 'w') as fout:
    fout.write("""Formal Power Series Computation Project
=======================================

Project database : project.db  (SQLite — query with sqlite3 CLI)
Polynomial data  : data/       (binary .poly files)
Algorithm notes  : notes/      (mathematical background)
Run logs         : logs/       (previous attempt output)
Output directory : output/

Computation tool : /app/bin/polytool
  Run 'polytool help' for available commands.
  Operates on binary .poly files.

STATUS: computation stalled — see journal in project.db for details.
""")

print("Workspace setup complete.")
