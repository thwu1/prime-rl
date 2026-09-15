#!/usr/bin/env python3
"""Generate challenge polynomials and pre-computed results with planted defects.

"""
import json
import math


def poly_from_roots(roots):
    """Compute polynomial coefficients from roots, descending order (highest degree first)."""
    coeffs = [1.0]
    for r in roots:
        new_coeffs = [0.0] * (len(coeffs) + 1)
        for i, c in enumerate(coeffs):
            new_coeffs[i] += c
            new_coeffs[i + 1] -= r * c
        coeffs = new_coeffs
    return coeffs


def chebyshev_coeffs(n):
    """Compute Chebyshev T_n(x) polynomial coefficients in descending order."""
    if n == 0:
        return [1.0]
    if n == 1:
        return [1.0, 0.0]
    t_prev = [0.0] * (n + 1)
    t_prev[0] = 1.0
    t_curr = [0.0] * (n + 1)
    t_curr[1] = 1.0
    for k in range(2, n + 1):
        t_next = [0.0] * (n + 1)
        for i in range(n):
            t_next[i + 1] += 2.0 * t_curr[i]
        for i in range(n + 1):
            t_next[i] -= t_prev[i]
        t_prev = t_curr[:]
        t_curr = t_next[:]
    return list(reversed(t_curr))


# ==================== POLYNOMIALS ====================

p1_coeffs = poly_from_roots([1, 2, 3, 4, 5])
p2_coeffs = [1.0, 3.0, -2.0, 7.0, -1.0, 5.0, -4.0]
p3_coeffs = poly_from_roots(list(range(1, 21)))
p4_coeffs = poly_from_roots([1, 1, 3, 5, 7])
p5_coeffs = chebyshev_coeffs(20)
p6_coeffs = [1.0] + [0.0] * 14 + [-1.0]

polynomials_data = {
    "polynomials": [
        {"name": "simple_quintic", "degree": 5,
         "coefficients_descending": p1_coeffs},
        {"name": "asymmetric_sextic", "degree": 6,
         "coefficients_descending": p2_coeffs},
        {"name": "wilkinson_20", "degree": 20,
         "coefficients_descending": p3_coeffs},
        {"name": "near_double", "degree": 5,
         "coefficients_descending": p4_coeffs},
        {"name": "chebyshev_20", "degree": 20,
         "coefficients_descending": p5_coeffs},
        {"name": "roots_of_unity", "degree": 15,
         "coefficients_descending": p6_coeffs},
    ]
}

# ==================== CLAIMED RESULTS (with planted defects) ====================

import numpy as np

claimed_results = {"results": []}

# 1. simple_quintic: CORRECT
claimed_results["results"].append({
    "name": "simple_quintic",
    "degree": 5,
    "roots": [{"re": float(r), "im": 0.0} for r in [1.0, 2.0, 3.0, 4.0, 5.0]],
    "status": "converged"
})

# 2. asymmetric_sextic: DEFECTIVE — roots computed from REVERSED coefficients
reversed_coeffs = list(reversed(p2_coeffs))
wrong_roots = np.roots(reversed_coeffs)
idx = np.lexsort((wrong_roots.imag, wrong_roots.real))
wrong_roots = wrong_roots[idx]
claimed_results["results"].append({
    "name": "asymmetric_sextic",
    "degree": 6,
    "roots": [{"re": float(z.real), "im": float(z.imag)} for z in wrong_roots],
    "status": "converged"
})

# 3. wilkinson_20: DEFECTIVE — root near x=12 dropped (only 19 roots)
w20_roots = np.roots(p3_coeffs)
idx = np.lexsort((w20_roots.imag, w20_roots.real))
w20_roots = w20_roots[idx]
filtered = []
removed = False
for z in w20_roots:
    if not removed and abs(z.real - 12.0) < 0.5 and abs(z.imag) < 0.5:
        removed = True
        continue
    filtered.append(z)
claimed_results["results"].append({
    "name": "wilkinson_20",
    "degree": 20,
    "roots": [{"re": float(z.real), "im": float(z.imag)} for z in filtered],
    "status": "converged"
})

# 4. near_double: DEFECTIVE — one double-root replaced with spurious value
claimed_results["results"].append({
    "name": "near_double",
    "degree": 5,
    "roots": [
        {"re": 1.0, "im": 0.0},
        {"re": 1.847, "im": 0.0},   # SPURIOUS — should be ~1.0
        {"re": 3.0, "im": 0.0},
        {"re": 5.0, "im": 0.0},
        {"re": 7.0, "im": 0.0},
    ],
    "status": "converged"
})

# 5. chebyshev_20: CORRECT
cheb_roots = sorted(math.cos((2 * k - 1) * math.pi / 40) for k in range(1, 21))
claimed_results["results"].append({
    "name": "chebyshev_20",
    "degree": 20,
    "roots": [{"re": r, "im": 0.0} for r in cheb_roots],
    "status": "converged"
})

# 6. roots_of_unity: CORRECT
rou = []
for k in range(15):
    angle = 2 * math.pi * k / 15
    rou.append({"re": float(math.cos(angle)), "im": float(math.sin(angle))})
rou.sort(key=lambda r: (r["re"], r["im"]))
claimed_results["results"].append({
    "name": "roots_of_unity",
    "degree": 15,
    "roots": rou,
    "status": "converged"
})

# ==================== WRITE FILES ====================

with open('/app/polynomials.json', 'w') as f:
    json.dump(polynomials_data, f, indent=2)

with open('/app/claimed_results.json', 'w') as f:
    json.dump(claimed_results, f, indent=2)

print("Generated /app/polynomials.json and /app/claimed_results.json")
for p in polynomials_data["polynomials"]:
    print(f"  {p['name']}: degree {p['degree']}")
