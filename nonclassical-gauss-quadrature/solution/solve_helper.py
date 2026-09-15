"""
Solution for nonclassical Gauss quadrature task.

Implements:
  1. Analytic moment computation via Gamma / Beta functions
  2. Stieltjes procedure (Gautschi's sigma-recurrence) in multiprecision
  3. Golub-Welsch algorithm (eigendecomposition of the Jacobi matrix)
  4. Quadrature evaluation of specified integrals

"""

import json
from mpmath import mp, mpf, matrix, gamma, pi, sin, cos, exp, besselj, nstr, sqrt

mp.dps = 120  # high internal precision to stabilise the Stieltjes procedure


# ---------------------------------------------------------------------------
# Moment computation
# ---------------------------------------------------------------------------

def compute_moments(w_name, count):
    """Return the first *count* moments mu_0 .. mu_{count-1}."""
    moments = []
    for k in range(count):
        if w_name == "w1":
            # w(x) = -ln(x) on (0,1): mu_k = 1/(k+1)^2
            moments.append(mpf(1) / (k + 1) ** 2)
        elif w_name == "w2":
            # w(x) = x^{-1/4}(1-x)^{1/3} on (0,1):
            # mu_k = B(k+3/4, 4/3) = Gamma(k+3/4)*Gamma(4/3) / Gamma(k+25/12)
            moments.append(
                gamma(k + mpf(3) / 4) * gamma(mpf(4) / 3) / gamma(k + mpf(25) / 12)
            )
        elif w_name == "w3":
            # w(x) = exp(-x^4) on (0,inf): mu_k = Gamma((k+1)/4) / 4
            moments.append(gamma((k + 1) / mpf(4)) / 4)
        else:
            raise ValueError(f"Unknown weight {w_name}")
    return moments


# ---------------------------------------------------------------------------
# Stieltjes procedure  (Gautschi, Theorem 2.32)
# ---------------------------------------------------------------------------

def stieltjes(moments, N):
    """Compute recurrence coefficients alpha_k, beta_k from power moments.

    The monic orthogonal polynomials P_k satisfy:
        P_{k+1}(x) = (x - alpha_k) P_k(x) - beta_k P_{k-1}(x)
    with P_{-1}=0, P_0=1.

    Returns (alpha, beta) each of length N.
    beta[0] = mu_0 (the zeroth moment / total weight).
    """
    sigma = {}
    alpha = [mpf(0)] * N
    beta_arr = [mpf(0)] * N

    # Initialise sigma table
    for l in range(2 * N):
        sigma[(-1, l)] = mpf(0)
        sigma[(0, l)] = moments[l]

    alpha[0] = moments[1] / moments[0]
    beta_arr[0] = moments[0]

    for k in range(1, N):
        for l in range(k, 2 * N - k):
            sigma[(k, l)] = (
                sigma[(k - 1, l + 1)]
                - alpha[k - 1] * sigma[(k - 1, l)]
                - beta_arr[k - 1] * sigma[(k - 2, l)]
            )
        alpha[k] = (
            sigma[(k, k + 1)] / sigma[(k, k)]
            - sigma[(k - 1, k)] / sigma[(k - 1, k - 1)]
        )
        beta_arr[k] = sigma[(k, k)] / sigma[(k - 1, k - 1)]

    return alpha, beta_arr


# ---------------------------------------------------------------------------
# Golub-Welsch algorithm
# ---------------------------------------------------------------------------

def golub_welsch(alpha, beta_arr, N):
    """Return (nodes, weights) for the N-point Gauss quadrature rule.

    Builds the symmetric tridiagonal Jacobi matrix from the recurrence
    coefficients alpha_k (diagonal) and sqrt(beta_{k+1}) (off-diagonal),
    then eigendecomposes it.

    nodes   = eigenvalues
    weights = mu_0 * (first eigenvector component)^2
    """
    J = matrix(N, N)
    for i in range(N):
        J[i, i] = alpha[i]
    for i in range(N - 1):
        off = sqrt(beta_arr[i + 1])
        J[i, i + 1] = off
        J[i + 1, i] = off

    eigenvalues, eigenvectors = mp.eigsy(J)

    nodes = list(eigenvalues)
    weights = [beta_arr[0] * eigenvectors[0, i] ** 2 for i in range(N)]

    # Sort by ascending node value
    pairs = sorted(zip(nodes, weights), key=lambda p: float(p[0]))
    nodes = [p[0] for p in pairs]
    weights = [p[1] for p in pairs]

    return nodes, weights


# ---------------------------------------------------------------------------
# Integrand evaluation
# ---------------------------------------------------------------------------

def eval_integrand(w_name, x):
    if w_name == "w1":
        return sin(pi * x) / (1 + x)
    elif w_name == "w2":
        return exp(x) * cos(pi * x)
    elif w_name == "w3":
        return besselj(0, x)
    raise ValueError(w_name)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    weight_names = ["w1", "w2", "w3"]
    orders = [4, 8, 16, 32]

    results = {
        "quadrature_rules": {},
        "integrals": {},
        "moment_check": {},
    }

    for w in weight_names:
        results["quadrature_rules"][w] = {}
        results["integrals"][w] = {}

        for N in orders:
            moments = compute_moments(w, 2 * N)
            alpha, beta_arr = stieltjes(moments, N)
            nodes, weights = golub_welsch(alpha, beta_arr, N)

            results["quadrature_rules"][w][str(N)] = {
                "nodes": [nstr(x, 35) for x in nodes],
                "weights": [nstr(x, 35) for x in weights],
            }

            # Evaluate the integral: sum w_i * f(x_i)
            integral_val = sum(
                wt * eval_integrand(w, nd) for nd, wt in zip(nodes, weights)
            )
            results["integrals"][w][str(N)] = nstr(integral_val, 35)

        # Moment check for N=32
        moments_64 = compute_moments(w, 64)
        nodes32 = [mpf(s) for s in results["quadrature_rules"][w]["32"]["nodes"]]
        weights32 = [mpf(s) for s in results["quadrature_rules"][w]["32"]["weights"]]
        max_rel = mpf(0)
        for k in range(64):
            computed = sum(wt * nd ** k for nd, wt in zip(nodes32, weights32))
            exact = moments_64[k]
            if abs(exact) > mpf("1e-100"):
                rel = abs(computed - exact) / abs(exact)
                if rel > max_rel:
                    max_rel = rel
        results["moment_check"][w] = nstr(max_rel, 6)

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == "__main__":
    main()
