"""
Solution for Newton-Schulz Quintic Iteration Coefficient Optimization.

"""

import json
import numpy as np
from scipy.optimize import minimize_scalar, minimize, differential_evolution

# ============================================================
# Problem parameters (mirrored from problem_spec.py)
# ============================================================

MUON_COEFFS = (3.4445, -4.7750, 2.0315)
MUON_N_ITERS = 5
MATRIX_SEED = 42
MATRIX_SHAPES = [(8, 6), (16, 16), (32, 16), (64, 64), (128, 64)]

P2_GRID = np.linspace(0.01, 1.0, 500)
P2_N_ITERS = 15
P2_TOLERANCE = 0.01
P2_DIVERGENCE_BOUND = 10.0

P3_GRID = np.linspace(0.01, 0.98, 500)
P3_N_COMPOSITIONS = 5
P3_LOWER_BOUND = 0.65
P3_UPPER_BOUND = 1.35
P3_DIVERGENCE_BOUND = 10.0


# ============================================================
# Core functions
# ============================================================

def apply_phi(x, a, b, c):
    """Apply quintic NS polynomial: phi(x) = a*x + b*x^3 + c*x^5."""
    return a * x + b * x**3 + c * x**5


def ns_iteration_matrix(G, a, b, c, n_iters):
    """Apply Newton-Schulz iteration to matrix G."""
    X = G.copy().astype(np.float64)
    X = X / (np.linalg.norm(X, "fro") + 1e-7)
    transposed = False
    if X.shape[0] > X.shape[1]:
        X = X.T
        transposed = True
    for _ in range(n_iters):
        A = X @ X.T
        B = b * A + c * A @ A
        X = a * X + B @ X
    if transposed:
        X = X.T
    return X


def true_polar_factor(G):
    """Compute polar factor U @ V.T via SVD."""
    U, S, Vt = np.linalg.svd(G, full_matrices=False)
    return U @ Vt


# ============================================================
# Part 1: Implementation & Verification
# ============================================================

def solve_part1():
    rng = np.random.default_rng(MATRIX_SEED)
    a, b, c = MUON_COEFFS
    errors = []
    for shape in MATRIX_SHAPES:
        G = rng.standard_normal(shape)
        X = ns_iteration_matrix(G, a, b, c, MUON_N_ITERS)
        P = true_polar_factor(G)
        err = np.linalg.norm(X - P, "fro")
        errors.append(float(err))
    return {"errors": errors}


# ============================================================
# Part 2: Fixed-Coefficient Optimization
# ============================================================

def check_p2_feasibility(c_param):
    """Check if coefficient c gives a feasible solution for Part 2.

    With constraints phi(1)=1 and phi'(1)=0:
        a = 3/2 + c
        b = -(1 + 4c) / 2
        a + b + c = 1  (verified)
        a + 3b + 5c = 0  (verified: phi'(1) = 0 for superlinear convergence)
    """
    a = 1.5 + c_param
    b = -(1.0 + 4.0 * c_param) / 2.0

    x = P2_GRID.copy()
    for k in range(P2_N_ITERS):
        x = apply_phi(x, a, b, c_param)
        if np.any(np.abs(x) >= P2_DIVERGENCE_BOUND):
            return False, float("inf")

    max_error = np.max(np.abs(x - 1.0))
    return max_error < P2_TOLERANCE, max_error


def solve_part2():
    """Find maximum a = 3/2 + c via bisection on c.

    The key insight: with phi(1)=1 and phi'(1)=0, convergence near x=1
    is quadratic (very fast). The bottleneck is (a) small x values needing
    many linear-growth steps, and (b) intermediate x values that may overshoot
    past the basin of attraction boundary.

    We use phi'(1)=0 to get the best convergence near 1, then maximize a
    subject to no divergence.
    """
    c_lo, c_hi = 0.1, 3.0  # a ranges from 1.6 to 4.5

    # First find the rough upper bound where feasibility fails
    while c_hi - c_lo > 0.001:
        feasible, _ = check_p2_feasibility(c_hi)
        if feasible:
            c_hi *= 1.5
            if c_hi > 100:
                break
        else:
            break

    # Bisection to find the maximum feasible c
    for _ in range(100):
        c_mid = (c_lo + c_hi) / 2.0
        feasible, max_err = check_p2_feasibility(c_mid)
        if feasible:
            c_lo = c_mid
        else:
            c_hi = c_mid
        if c_hi - c_lo < 1e-6:
            break

    # Use the conservative lower bound
    c_opt = c_lo
    a_opt = 1.5 + c_opt
    b_opt = -(1.0 + 4.0 * c_opt) / 2.0

    # Verify and compute max_error
    x = P2_GRID.copy()
    for _ in range(P2_N_ITERS):
        x = apply_phi(x, a_opt, b_opt, c_opt)
    max_error = float(np.max(np.abs(x - 1.0)))

    return {
        "coefficients": [float(a_opt), float(b_opt), float(c_opt)],
        "max_error": max_error,
        "a_value": float(a_opt),
    }


# ============================================================
# Part 3: Per-Iteration Coefficient Optimization
# ============================================================

def check_p3_feasibility(coeffs_flat):
    """Check feasibility and return max deviation for Part 3.

    coeffs_flat: array of 15 values [a1,b1,c1, a2,b2,c2, ..., a5,b5,c5]
    """
    coeffs = coeffs_flat.reshape(5, 3)
    x = P3_GRID.copy()
    for i in range(5):
        a, b, c = coeffs[i]
        x = apply_phi(x, a, b, c)
        if np.any(np.abs(x) >= P3_DIVERGENCE_BOUND):
            return False, float("inf"), float("inf")

    max_val = np.max(x)
    min_val = np.min(x)
    feasible = (min_val >= P3_LOWER_BOUND) and (max_val <= P3_UPPER_BOUND)
    max_dev = max(abs(max_val - 1.0), abs(min_val - 1.0))
    return feasible, max_dev, float(np.prod(coeffs[:, 0]))


def solve_part3_sequential():
    """Optimize per-iteration coefficients sequentially.

    Strategy: optimize one polynomial at a time, from first to last.
    The first polynomial should maximize slope at zero (large a_1) to
    quickly boost small values. Later polynomials refine toward 1.

    We use a greedy approach: for each step, find the polynomial that
    maximizes a_i while keeping the partial composition well-behaved.
    """
    best_coeffs = []

    # Start with the grid
    current_x = P3_GRID.copy()
    x_target_lower = P3_LOWER_BOUND
    x_target_upper = P3_UPPER_BOUND

    for step in range(5):
        remaining_steps = 5 - step - 1

        def neg_a_objective(params):
            a, b, c = params
            x = apply_phi(current_x, a, b, c)
            if np.any(np.abs(x) >= P3_DIVERGENCE_BOUND):
                return 1e10
            if np.any(~np.isfinite(x)):
                return 1e10
            # If this is the last step, check final constraint
            if remaining_steps == 0:
                if np.min(x) < x_target_lower or np.max(x) > x_target_upper:
                    return 1e10
            else:
                # Intermediate: don't let values get too extreme
                # but allow some room for later correction
                if np.max(x) > 5.0 or np.min(x) < -1.0:
                    return 1e10
            return -a  # maximize a

        # Try many starting points
        best_a = -1e10
        best_params = None

        # Search over a range of (a, b, c) values
        for a_init in np.linspace(1.0, 15.0, 30):
            for bc_ratio in np.linspace(-10.0, 5.0, 25):
                b_init = bc_ratio
                c_init = a_init - 1 - b_init  # try a+b+c near 1
                try:
                    res = minimize(
                        neg_a_objective,
                        [a_init, b_init, c_init],
                        method="Nelder-Mead",
                        options={"maxiter": 500, "xatol": 1e-6, "fatol": 1e-8},
                    )
                    if res.fun < -best_a:
                        test_x = apply_phi(current_x, *res.x)
                        if np.all(np.isfinite(test_x)) and np.all(np.abs(test_x) < P3_DIVERGENCE_BOUND):
                            best_a = -res.fun
                            best_params = res.x.copy()
                except Exception:
                    pass

        # Fallback: if nothing found, use Muon-like coefficients
        if best_params is None:
            best_params = np.array([3.4445, -4.7750, 2.0315])

        best_coeffs.append(best_params.tolist())
        current_x = apply_phi(current_x, *best_params)

    return best_coeffs


def solve_part3_global():
    """Global optimization approach using differential evolution."""

    def objective(coeffs_flat):
        coeffs = coeffs_flat.reshape(5, 3)
        x = P3_GRID.copy()
        for i in range(5):
            a, b, c = coeffs[i]
            x = apply_phi(x, a, b, c)
            if np.any(np.abs(x) >= P3_DIVERGENCE_BOUND) or np.any(~np.isfinite(x)):
                return 1e10

        min_val, max_val = np.min(x), np.max(x)
        if min_val < P3_LOWER_BOUND or max_val > P3_UPPER_BOUND:
            # Penalty proportional to constraint violation
            violation = max(P3_LOWER_BOUND - min_val, max_val - P3_UPPER_BOUND, 0)
            return 1e5 * violation - np.sum(np.log(np.maximum(coeffs[:, 0], 1e-10)))

        # Feasible: maximize product of slopes = maximize sum of log(a_i)
        log_product = np.sum(np.log(np.maximum(coeffs[:, 0], 1e-10)))
        return -log_product

    # Bounds: a in [1, 12], b in [-30, 5], c in [-5, 25]
    bounds = []
    for _ in range(5):
        bounds.extend([(1.0, 12.0), (-30.0, 5.0), (-5.0, 25.0)])

    result = differential_evolution(
        objective,
        bounds,
        seed=123,
        maxiter=1000,
        tol=1e-8,
        popsize=30,
        mutation=(0.5, 1.5),
        recombination=0.9,
    )

    return result.x.reshape(5, 3).tolist()


def solve_part3():
    """Solve Part 3 using both sequential and global approaches, take the best."""

    # Try sequential approach
    seq_coeffs = solve_part3_sequential()
    seq_feasible, seq_dev, seq_prod = check_p3_feasibility(np.array(seq_coeffs).flatten())

    # Try global approach
    glob_coeffs = solve_part3_global()
    glob_feasible, glob_dev, glob_prod = check_p3_feasibility(np.array(glob_coeffs).flatten())

    # Pick the best feasible solution
    if seq_feasible and glob_feasible:
        if seq_prod > glob_prod:
            coeffs = seq_coeffs
        else:
            coeffs = glob_coeffs
    elif seq_feasible:
        coeffs = seq_coeffs
    elif glob_feasible:
        coeffs = glob_coeffs
    else:
        # Fallback: use Muon coefficients (uniform) for all 5
        coeffs = [list(MUON_COEFFS)] * 5

    coeffs_arr = np.array(coeffs)
    product = float(np.prod(coeffs_arr[:, 0]))

    # Compute max error
    x = P3_GRID.copy()
    for a, b, c in coeffs:
        x = apply_phi(x, a, b, c)
    max_error = float(np.max(np.abs(x - 1.0)))

    return {
        "coefficients": [[float(v) for v in triple] for triple in coeffs],
        "product_of_slopes": product,
        "max_error": max_error,
    }


# ============================================================
# Main
# ============================================================

def main():
    print("Solving Part 1: NS Implementation & Verification...")
    part1 = solve_part1()
    print(f"  Errors: {part1['errors']}")

    print("Solving Part 2: Fixed-Coefficient Optimization...")
    part2 = solve_part2()
    print(f"  a = {part2['a_value']:.6f}, max_error = {part2['max_error']:.8f}")

    print("Solving Part 3: Per-Iteration Coefficient Optimization...")
    part3 = solve_part3()
    print(f"  Product of slopes = {part3['product_of_slopes']:.4f}")
    print(f"  Max error = {part3['max_error']:.6f}")

    results = {"part1": part1, "part2": part2, "part3": part3}

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults written to /app/results.json")


if __name__ == "__main__":
    main()
