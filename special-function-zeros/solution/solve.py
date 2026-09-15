"""

Compute eigenvalues (zeros of secular equations) for annular membrane
boundary value problems, the spectral zeta function Z_4, and McMahon
asymptotic convergence products.
"""

import json
from mpmath import mp, mpf, besselj, bessely, diff, fabs, pi


# ── Secular equation definitions ────────────────────────────────────────


def annular_m0(x):
    """J_0(3x)*Y_0(x) - Y_0(3x)*J_0(x): Dirichlet eigenvalues, m=0, annulus [1,3]."""
    return besselj(0, 3 * x) * bessely(0, x) - bessely(0, 3 * x) * besselj(0, x)


def annular_m1(x):
    """J_1(3x)*Y_1(x) - Y_1(3x)*J_1(x): Dirichlet eigenvalues, m=1, annulus [1,3]."""
    return besselj(1, 3 * x) * bessely(1, x) - bessely(1, 3 * x) * besselj(1, x)


def robin_dirichlet(x):
    """Robin-Dirichlet secular equation on annulus [1,2], Biot h=5.
    h(x) = x*[J_0(2x)*Y_1(x) - J_1(x)*Y_0(2x)] - 5*[J_0(x)*Y_0(2x) - J_0(2x)*Y_0(x)]
    Derived from u(r) = A*J_0(lr) + B*Y_0(lr) with du/dn + 5u = 0 at r=1, u=0 at r=2.
    """
    return (
        x * (besselj(0, 2 * x) * bessely(1, x) - besselj(1, x) * bessely(0, 2 * x))
        - 5 * (besselj(0, x) * bessely(0, 2 * x) - besselj(0, 2 * x) * bessely(0, x))
    )


# ── Root-finding utilities ──────────────────────────────────────────────


def grid_search(f, a, b, n_grid=10000):
    """Identify sign-change intervals at moderate precision."""
    saved = mp.dps
    mp.dps = 30
    intervals = []
    xa = mpf(a)
    step = (mpf(b) - xa) / n_grid
    prev = f(xa)
    for i in range(1, n_grid + 1):
        xi = xa + step * i
        cur = f(xi)
        if prev * cur < 0:
            intervals.append((float(xa + step * (i - 1)), float(xi)))
        prev = cur
    mp.dps = saved
    return intervals


def newton_refine(f, x0, target_digits=65, max_iter=300):
    """Refine a root via Newton's method with numerical differentiation."""
    saved = mp.dps
    mp.dps = target_digits + 20
    x = mpf(x0)
    tol = mpf(10) ** (-(target_digits + 10))
    iters = 0
    for it in range(1, max_iter + 1):
        fx = f(x)
        fpx = diff(f, x)
        if fpx == 0:
            break
        delta = fx / fpx
        x = x - delta
        iters = it
        if fabs(delta) < tol * fabs(x):
            break
    mp.dps = saved
    return x, iters


def find_zeros(f, a, b, n_zeros, n_grid=10000):
    """Locate zeros via grid search followed by Newton refinement."""
    intervals = grid_search(f, a, b, n_grid)
    zeros = []
    for lo, hi in intervals:
        x0 = (lo + hi) / 2.0
        z, iters = newton_refine(f, x0)
        mp.dps = 80
        residual = fabs(f(z))
        mp.dps = 75
        zeros.append((z, residual, iters))
    zeros.sort(key=lambda t: float(t[0]))
    return zeros[:n_zeros]


# ── Main computation ────────────────────────────────────────────────────


def main():
    mp.dps = 80

    problems_config = [
        ("annular_m0", annular_m0, 0.1, 50.0, 15),
        ("annular_m1", annular_m1, 0.1, 50.0, 15),
        ("robin_dirichlet", robin_dirichlet, 0.5, 35.0, 10),
    ]

    output = {"problems": []}
    all_zeros = {}

    for prob_id, f, a, b, n_zeros in problems_config:
        print(f"Solving {prob_id}: {n_zeros} zeros in [{a}, {b}]")
        zeros = find_zeros(f, a, b, n_zeros)
        all_zeros[prob_id] = zeros

        mp.dps = 80
        zero_entries = []
        for i, (z, res, iters) in enumerate(zeros):
            value_str = mp.nstr(z, 68)
            zero_entries.append(
                {
                    "index": i + 1,
                    "value": value_str,
                    "residual": f"{float(res):.6e}",
                }
            )
            print(
                f"  #{i+1}: {value_str[:45]}... residual={float(res):.2e} iters={iters}"
            )

        output["problems"].append({"id": prob_id, "zeros": zero_entries})

    # ── Spectral zeta function Z_4 ──────────────────────────────────────
    mp.dps = 70
    Z4 = mpf(0)

    # m=0 annular: multiplicity 1
    for z, _, _ in all_zeros["annular_m0"]:
        Z4 += 1 / z ** 4

    # m=1 annular: multiplicity 2
    for z, _, _ in all_zeros["annular_m1"]:
        Z4 += 2 / z ** 4

    # Robin-Dirichlet: multiplicity 1
    for z, _, _ in all_zeros["robin_dirichlet"]:
        Z4 += 1 / z ** 4

    output["spectral_zeta_Z4"] = mp.nstr(Z4, 55)
    print(f"\nZ_4 = {mp.nstr(Z4, 55)}")

    # ── McMahon asymptotic convergence products ─────────────────────────
    mp.dps = 70
    asymp_products = []
    for i, (z, _, _) in enumerate(all_zeros["annular_m0"]):
        n = i + 1
        asymp_pred = n * pi / 2
        rel_error = fabs(z - asymp_pred) / z
        Pn = n ** 2 * rel_error
        asymp_products.append(
            {
                "n": n,
                "product": mp.nstr(Pn, 20),
                "zero_value": mp.nstr(z, 68),
            }
        )
        print(f"  P_{n} = {float(Pn):.12f}")

    output["asymptotic_products"] = asymp_products

    with open("/app/results.json", "w") as fout:
        json.dump(output, fout, indent=2)

    print("\nResults written to /app/results.json")


if __name__ == "__main__":
    main()
