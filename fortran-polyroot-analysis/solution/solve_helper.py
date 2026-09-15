#!/usr/bin/env python3
"""Solution: Audit polynomial root-finding results, diagnose defects, compare algorithms.

"""
import json
import math


def eval_poly_horner(coeffs_desc, z):
    """Evaluate polynomial at complex z using Horner's method.
    coeffs_desc: descending order [a_n, a_{n-1}, ..., a_0]."""
    result = complex(coeffs_desc[0])
    for c in coeffs_desc[1:]:
        result = result * z + complex(c)
    return result


def backward_error(coeffs_desc, z):
    """Componentwise relative backward error: |p(z)| / sum(|a_k||z|^k)."""
    pz = eval_poly_horner(coeffs_desc, z)
    n = len(coeffs_desc) - 1
    az = abs(z)
    denom = sum(abs(coeffs_desc[i]) * (az ** (n - i)) for i in range(n + 1))
    if denom < 1e-300:
        return abs(pz)
    return abs(pz) / denom


def aberth_ehrlich(coeffs_desc, max_iter=2000, tol=1e-14):
    """Aberth-Ehrlich simultaneous iteration for all polynomial roots."""
    n = len(coeffs_desc) - 1
    if n == 0:
        return []

    lc = coeffs_desc[0]
    coeffs = [c / lc for c in coeffs_desc]

    # Derivative coefficients (descending)
    deriv = [(n - i) * coeffs[i] for i in range(n)]

    # Initial guesses on a circle
    r0 = 1.0 + max(abs(c) for c in coeffs[1:])
    roots = []
    for k in range(n):
        angle = 2 * math.pi * k / n + 0.4
        roots.append(complex(r0 * math.cos(angle), r0 * math.sin(angle)))

    for _ in range(max_iter):
        max_change = 0.0
        for i in range(n):
            pz = eval_poly_horner(coeffs, roots[i])
            dpz = eval_poly_horner(deriv, roots[i])
            if abs(dpz) < 1e-300:
                continue
            ratio = pz / dpz
            s = sum(1.0 / (roots[i] - roots[j])
                    for j in range(n) if j != i and abs(roots[i] - roots[j]) > 1e-300)
            denom = 1.0 - ratio * s
            if abs(denom) < 1e-300:
                correction = ratio
            else:
                correction = ratio / denom
            roots[i] -= correction
            max_change = max(max_change, abs(correction))
        if max_change < tol:
            break

    return roots


def main():
    import numpy as np

    with open('/app/polynomials.json') as f:
        poly_data = json.load(f)
    with open('/app/claimed_results.json') as f:
        claimed_data = json.load(f)

    polys = {p["name"]: p for p in poly_data["polynomials"]}
    claimed = {r["name"]: r for r in claimed_data["results"]}

    defective = []
    correct = []
    defects = {}
    corrected_roots = {}

    # ==================== PHASE 1: AUDIT CLAIMED RESULTS ====================

    for name, poly in polys.items():
        coeffs = poly["coefficients_descending"]
        degree = poly["degree"]
        claim = claimed[name]

        # Check root count vs degree
        if len(claim["roots"]) != degree:
            defective.append(name)
            true_roots = np.roots(coeffs)
            claimed_complex = [complex(r["re"], r["im"]) for r in claim["roots"]]
            missing_vals = []
            for tr in true_roots:
                closest = min(abs(tr - cr) for cr in claimed_complex) if claimed_complex else float('inf')
                if closest > 1.0:
                    missing_vals.append(tr)
            missing_approx = missing_vals[0].real if missing_vals else 0
            defects[name] = {
                "type": "missing_root",
                "detail": (f"Only {len(claim['roots'])} roots reported for degree-{degree} "
                           f"polynomial. Root near x={missing_approx:.1f} is absent, likely "
                           f"lost due to ill-conditioning in the high-sensitivity region.")
            }
            continue

        # Check backward error for each claimed root
        max_be = 0.0
        worst_idx = -1
        for i, root in enumerate(claim["roots"]):
            z = complex(root["re"], root["im"])
            be = backward_error(coeffs, z)
            if be > max_be:
                max_be = be
                worst_idx = i

        if max_be > 1e-4:
            defective.append(name)

            # Diagnostic: check if roots satisfy the REVERSED polynomial
            reversed_coeffs = list(reversed(coeffs))
            max_be_rev = max(
                backward_error(reversed_coeffs, complex(r["re"], r["im"]))
                for r in claim["roots"]
            )

            if max_be_rev < 1e-8:
                defects[name] = {
                    "type": "coefficient_ordering_reversed",
                    "detail": (f"Claimed roots satisfy the coefficient-reversed polynomial "
                               f"(ascending instead of descending order). Backward error "
                               f"against original: {max_be:.2e}, against reversed: "
                               f"{max_be_rev:.2e}. This indicates the root-finding algorithm "
                               f"received coefficients in the wrong ordering convention.")
                }
            else:
                # Individual root failure
                bad = [(i, claim["roots"][i], backward_error(coeffs, complex(claim["roots"][i]["re"], claim["roots"][i]["im"])))
                       for i in range(len(claim["roots"]))
                       if backward_error(coeffs, complex(claim["roots"][i]["re"], claim["roots"][i]["im"])) > 1e-4]
                r0 = bad[0] if bad else (worst_idx, claim["roots"][worst_idx], max_be)
                defects[name] = {
                    "type": "convergence_failure_spurious_root",
                    "detail": (f"Root index {r0[0]} at z={r0[1]['re']:.4f}+{r0[1]['im']:.4f}i "
                               f"has backward error {r0[2]:.2e}, indicating the algorithm "
                               f"did not converge to a true root (likely near a multiple root "
                               f"where convergence is degraded).")
                }
        else:
            correct.append(name)

    # ==================== PHASE 2: COMPUTE CORRECTED ROOTS ====================

    for name, poly in polys.items():
        coeffs = poly["coefficients_descending"]
        roots = np.roots(coeffs)
        idx = np.lexsort((roots.imag, roots.real))
        roots = roots[idx]
        corrected_roots[name] = [
            {"re": float(z.real), "im": float(z.imag)} for z in roots
        ]

    # ==================== PHASE 3: ALGORITHM COMPARISON ====================

    from numpy.polynomial.polynomial import polyroots as np_polyroots

    algo_comparison = {
        "companion_matrix": {},
        "numpy_polynomial_polyroots": {},
        "aberth_ehrlich": {},
    }

    for name, poly in polys.items():
        coeffs = poly["coefficients_descending"]
        degree = poly["degree"]

        # Algorithm 1: numpy.roots (companion matrix eigenvalues, LAPACK)
        roots1 = np.roots(coeffs)
        be1 = [backward_error(coeffs, z) for z in roots1]
        algo_comparison["companion_matrix"][name] = {
            "max_backward_error": float(max(be1)),
            "num_accurate_roots": sum(1 for b in be1 if b < 1e-6)
        }

        # Algorithm 2: numpy.polynomial.polynomial.polyroots (ascending coefficients)
        ascending = list(reversed(coeffs))
        try:
            roots2 = np_polyroots(ascending)
            be2 = [backward_error(coeffs, z) for z in roots2]
            algo_comparison["numpy_polynomial_polyroots"][name] = {
                "max_backward_error": float(max(be2)),
                "num_accurate_roots": sum(1 for b in be2 if b < 1e-6)
            }
        except Exception:
            algo_comparison["numpy_polynomial_polyroots"][name] = {
                "max_backward_error": 1e30,
                "num_accurate_roots": 0
            }

        # Algorithm 3: Aberth-Ehrlich simultaneous iteration
        try:
            roots3 = aberth_ehrlich(coeffs)
            be3 = [backward_error(coeffs, z) for z in roots3]
            algo_comparison["aberth_ehrlich"][name] = {
                "max_backward_error": float(max(be3)) if be3 else 1e30,
                "num_accurate_roots": sum(1 for b in be3 if b < 1e-6)
            }
        except Exception:
            algo_comparison["aberth_ehrlich"][name] = {
                "max_backward_error": 1e30,
                "num_accurate_roots": 0
            }

    # Determine best algorithm by total accurate roots, tiebreak by max error
    def score(algo):
        data = algo_comparison[algo]
        total = sum(d["num_accurate_roots"] for d in data.values())
        worst = max(d["max_backward_error"] for d in data.values())
        return (total, -worst)

    best_algo = max(algo_comparison.keys(), key=score)

    # ==================== WRITE OUTPUT ====================

    audit = {
        "defective_polynomials": defective,
        "correct_polynomials": correct,
        "defects": defects,
        "corrected_roots": corrected_roots,
        "algorithm_comparison": algo_comparison,
        "best_algorithm": best_algo,
    }

    with open('/app/audit.json', 'w') as f:
        json.dump(audit, f, indent=2)

    print("Audit written to /app/audit.json")
    print(f"Defective: {defective}")
    print(f"Correct: {correct}")
    for n, d in defects.items():
        print(f"  {n}: {d['type']}")
    print(f"Best algorithm: {best_algo}")


if __name__ == "__main__":
    main()
