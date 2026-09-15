#!/usr/bin/env python3

"""
Fix the three precision bugs in the oracle.

Bug 1 (log1p): log(1+x) suffers catastrophic cancellation for small x because
the addition 1+x rounds away x at the current working precision. The fix is to
use mpmath's log1p(x), which uses a compensated algorithm that avoids the
cancellation entirely.

Bug 2 (zeta): The Euler product over 200 primes gives only ~4 correct
significant digits regardless of working precision, because the tail
contribution from all primes > 1223 is O(10^{-4}) for s=2. The fix is to use
mpmath's built-in zeta(s) which employs the Euler-Maclaurin formula with
analytic continuation.

Bug 3 (hilbert_det): Computing det(H_n) at dps=output_dps loses approximately
log10(cond(H_n)) significant digits due to cancellation in LU decomposition.
For n=15, cond(H_15) ~ 10^20, so ~20 digits are lost. The fix is to increase
the working precision proportionally to n.
"""

with open("/app/precision_oracle.py") as f:
    code = f.read()

# Fix 1: Add log1p and zeta to imports
code = code.replace(
    "from mpmath import mp, mpf, log, power, matrix, det, nstr",
    "from mpmath import mp, mpf, log, log1p, power, matrix, det, nstr, zeta",
)

# Fix 1: Use log1p(x) instead of log(1 + x) to avoid catastrophic cancellation
code = code.replace(
    "        val = log(mpf(1) + x)\n",
    "        val = log1p(x)\n",
)

# Fix 2: Use mpmath's built-in zeta instead of truncated Euler product
code = code.replace(
    "        val = _euler_product_zeta(s, num_primes=200)\n",
    "        val = zeta(s)\n",
)

# Fix 3: Scale working precision with matrix size to compensate for
# the condition number of Hilbert matrices (cond ~ e^{3.5n})
code = code.replace(
    "        mp.dps = output_dps\n        H = matrix(n, n)",
    "        mp.dps = output_dps + 20 * n\n        H = matrix(n, n)",
)

with open("/app/precision_oracle.py", "w") as f:
    f.write(code)

print("Oracle fixed: log1p cancellation, zeta Euler product, Hilbert precision")
