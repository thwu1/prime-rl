#!/usr/bin/env python3

"""
Fix the 4 mathematical bugs in /app/reserving.R.

Bug 1 (mack_recursive_se, process risk):
  The second term in the process risk recursion uses f[k] instead of f[k]^2.
  Mack (1993) Eq. 4: mse(C_{i,k+1}) = C_{i,k}^2 * F.se_{i,k}^2 + f_k^2 * mse(C_{i,k})
  The code has: procrisk^2 * f[k]    -- missing the square on f[k]
  Fix:          procrisk^2 * f[k]^2

Bug 2 (mack_recursive_se, parameter risk):
  The first term in the parameter risk recursion is missing the C_{i,k}^2 multiplier.
  Mack (1993): parameter_risk(C_{i,k+1}) = C_{i,k}^2 * f.se_k^2 + f_k^2 * parameter_risk(C_{i,k})
  The code has: f.se[k]^2                    -- missing FullTriangle[i,k]^2
  Fix:          FullTriangle[i,k]^2 * f.se[k]^2

Bug 3 (total_mack_se, M vector):
  M[k] should sum over rows that are still being developed at column k,
  i.e., rows (m+1-k):m. The code sums rows 1:k instead.
  The code has: FullTriangle[1:k, k]
  Fix:          FullTriangle[(m + 1 - k):m, k]

Bug 4 (mack_skewness, Sk3k denominator):
  The Sk3k (third central moment) computation uses a simplified denominator (n-i)
  instead of the correct bias-corrected denominator from Dal Moro's paper.
  The code has: 1/(n - i)
  Fix:          1/(n - i - Interm1[i]^2/Interm2[i]^3)
"""

import sys

with open('/app/reserving.R', 'r') as f:
    code = f.read()

original = code

# Bug 1: Process risk - f[k] should be f[k]^2
old1 = 'procrisk[i, k+1] <- sqrt(FullTriangle[i,k]^2 * F.se[i,k]^2 + procrisk[i,k]^2 * f[k])'
new1 = 'procrisk[i, k+1] <- sqrt(FullTriangle[i,k]^2 * F.se[i,k]^2 + procrisk[i,k]^2 * f[k]^2)'
assert old1 in code, "Bug 1 pattern not found"
code = code.replace(old1, new1)

# Bug 2: Parameter risk - missing FullTriangle[i,k]^2 multiplier
old2 = 'paramrisk[i, k+1] <- sqrt(f.se[k]^2 + paramrisk[i,k]^2 * f[k]^2)'
new2 = 'paramrisk[i, k+1] <- sqrt(FullTriangle[i,k]^2 * f.se[k]^2 + paramrisk[i,k]^2 * f[k]^2)'
assert old2 in code, "Bug 2 pattern not found"
code = code.replace(old2, new2)

# Bug 3: Total M vector - wrong row indices
old3 = 'M <- sapply(1:n, function(k) sum(FullTriangle[1:k, k], na.rm = TRUE))'
new3 = 'M <- sapply(1:n, function(k) sum(FullTriangle[(m + 1 - k):m, k], na.rm = TRUE))'
assert old3 in code, "Bug 3 pattern not found"
code = code.replace(old3, new3)

# Bug 4: Skewness Sk3k denominator
old4 = '1/(n - i) * sum(Triangle[1:(n-i), i]^1.5 * myModel[1:(n-i), i]^3)'
new4 = '1/(n - i - Interm1[i]^2/Interm2[i]^3) * sum(Triangle[1:(n-i), i]^1.5 * myModel[1:(n-i), i]^3)'
assert old4 in code, "Bug 4 pattern not found"
code = code.replace(old4, new4)

assert code != original, "No changes were made"

with open('/app/reserving.R', 'w') as f:
    f.write(code)

print("All 4 mathematical bugs fixed in /app/reserving.R")
print("  1. Process risk: f[k] -> f[k]^2")
print("  2. Parameter risk: added FullTriangle[i,k]^2 multiplier")
print("  3. Total M vector: 1:k -> (m+1-k):m")
print("  4. Sk3k denominator: (n-i) -> (n-i-Interm1[i]^2/Interm2[i]^3)")
