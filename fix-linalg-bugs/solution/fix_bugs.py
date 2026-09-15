"""
Fix three numerical bugs in /app/linalg.py.

Bug 1 (householder_qr_solve): mpmath.sign(0) returns 0, collapsing the
Householder reflection vector to zero when a diagonal pivot is exactly zero.
Fix: default sign to +1.

Bug 2 (cholesky_solve): Back-substitution uses L[j,i] (transpose) instead
of conj(L[j,i]) (conjugate transpose). Invisible for real matrices but
wrong for complex Hermitian systems.

Bug 3 (_factor_complex): Subdiagonal norm uses z*z instead of z*conj(z),
computing z^2 (complex) rather than |z|^2 (real positive). Breaks complex
QR factorization.

"""

with open('/app/linalg.py', 'r') as f:
    code = f.read()

# --- Fix 1: Householder zero-pivot sign convention ---
old1 = (
    "        # Choose sign for numerical stability\n"
    "        p.append(-mpmath.sign(mpmath.re(Aug[j, j])) * mpmath.sqrt(s))"
)
new1 = (
    "        # Choose sign for numerical stability (default to +1 at zero)\n"
    "        sign_val = mpmath.sign(mpmath.re(Aug[j, j]))\n"
    "        if sign_val == 0:\n"
    "            sign_val = mpmath.mpf(1)\n"
    "        p.append(-sign_val * mpmath.sqrt(s))"
)
assert old1 in code, "Fix 1: target string not found"
code = code.replace(old1, new1)

# --- Fix 2: Cholesky back-substitution conjugate transpose ---
old2 = "x[i] -= mpmath.fsum(L[j, i] * x[j] for j in range(i + 1, n))"
new2 = "x[i] -= mpmath.fsum(mpmath.conj(L[j, i]) * x[j] for j in range(i + 1, n))"
assert old2 in code, "Fix 2: target string not found"
code = code.replace(old2, new2)

# --- Fix 3: Complex QR norm conjugation ---
old3 = (
    "            xnorm = mpmath.fsum(\n"
    "                A[i, j] * A[i, j] for i in range(j + 1, m)\n"
    "            )"
)
new3 = (
    "            xnorm = mpmath.fsum(\n"
    "                A[i, j] * mpmath.conj(A[i, j]) for i in range(j + 1, m)\n"
    "            )"
)
assert old3 in code, "Fix 3: target string not found"
code = code.replace(old3, new3)

with open('/app/linalg.py', 'w') as f:
    f.write(code)

print("All three bugs fixed successfully.")
