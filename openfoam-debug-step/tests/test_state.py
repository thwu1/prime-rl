"""
Tests for the 1D Euler equation (Sod shock tube) finite volume solver task.

Verifies the numerical solution against known exact analytical values for the
Sod shock tube problem at t=0.2 with gamma=1.4.

"""

import json
import os
import csv
import math
import pytest

# Exact Sod shock tube values at t=0.2, gamma=1.4
# Left: rho=1, u=0, p=1   Right: rho=0.125, u=0, p=0.1
EXACT_SHOCK_POS = 0.8504
EXACT_CONTACT_POS = 0.6855
EXACT_STAR_VEL = 0.92745
EXACT_RHO_STAR_R = 0.26557
EXACT_P_STAR = 0.30313
EXACT_RHO_STAR_L = 0.42632
EXACT_TOTAL_MASS = 0.5625


def load_results():
    with open("/app/results.json") as f:
        return json.load(f)


def load_solution_csv():
    rows = []
    with open("/app/solution.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                'x': float(row['x']),
                'rho': float(row['rho']),
                'u': float(row['u']),
                'p': float(row['p']),
            })
    return rows


# ---------- results.json format tests ----------

def test_results_file_exists():
    """results.json must exist."""
    assert os.path.exists("/app/results.json"), \
        "results.json not found at /app/results.json"


def test_results_has_required_keys():
    """results.json must contain all required keys with numeric values."""
    data = load_results()
    required = [
        "shock_position", "contact_position", "post_shock_density",
        "post_shock_pressure", "star_velocity", "density_l2_error",
        "total_mass", "n_cells"
    ]
    for key in required:
        assert key in data, f"Missing key: {key}"
        assert isinstance(data[key], (int, float)), \
            f"{key} must be numeric, got {type(data[key]).__name__}"


def test_n_cells():
    """Grid resolution must be exactly 400."""
    data = load_results()
    assert data["n_cells"] == 400, f"n_cells = {data['n_cells']}, expected 400"


# ---------- Physical accuracy tests ----------

def test_shock_position():
    """Shock position must be within tolerance of exact value ~0.8504."""
    data = load_results()
    val = data["shock_position"]
    assert 0.82 <= val <= 0.88, \
        f"Shock position {val:.4f} outside expected range [0.82, 0.88]"


def test_contact_position():
    """Contact discontinuity position must be near exact value ~0.6855."""
    data = load_results()
    val = data["contact_position"]
    assert 0.66 <= val <= 0.72, \
        f"Contact position {val:.4f} outside expected range [0.66, 0.72]"


def test_star_velocity():
    """Star-region velocity must match exact value ~0.92745."""
    data = load_results()
    val = data["star_velocity"]
    assert 0.88 <= val <= 0.97, \
        f"Star velocity {val:.5f} outside expected range [0.88, 0.97]"


def test_post_shock_density():
    """Post-shock density must be near exact value ~0.26557."""
    data = load_results()
    val = data["post_shock_density"]
    assert 0.23 <= val <= 0.30, \
        f"Post-shock density {val:.4f} outside expected range [0.23, 0.30]"


def test_post_shock_pressure():
    """Post-shock pressure must be near exact value ~0.30313."""
    data = load_results()
    val = data["post_shock_pressure"]
    assert 0.27 <= val <= 0.34, \
        f"Post-shock pressure {val:.4f} outside expected range [0.27, 0.34]"


def test_l2_error_small():
    """Density L2 error must be below 0.05 (2nd-order accuracy with 400 cells)."""
    data = load_results()
    val = data["density_l2_error"]
    assert val < 0.05, f"Density L2 error {val:.6f} exceeds threshold 0.05"


def test_mass_conservation():
    """Total mass must equal initial mass 0.5625 (FVM is conservative)."""
    data = load_results()
    val = data["total_mass"]
    assert abs(val - EXACT_TOTAL_MASS) < 1e-4, \
        f"Total mass {val:.8f} differs from expected {EXACT_TOTAL_MASS} by " \
        f"{abs(val - EXACT_TOTAL_MASS):.2e}"


# ---------- Solution CSV tests ----------

def test_solution_csv_exists():
    """solution.csv must exist."""
    assert os.path.exists("/app/solution.csv"), \
        "solution.csv not found at /app/solution.csv"


def test_solution_csv_format():
    """solution.csv must have correct header and 400 data rows."""
    with open("/app/solution.csv") as f:
        reader = csv.reader(f)
        header = next(reader)
        assert header == ['x', 'rho', 'u', 'p'], \
            f"CSV header must be ['x', 'rho', 'u', 'p'], got {header}"
        rows = list(reader)
        assert len(rows) == 400, f"Expected 400 data rows, got {len(rows)}"


def test_undisturbed_left_state():
    """Density in undisturbed left region (x < 0.2) must be ~1.0."""
    rows = load_solution_csv()
    for row in rows:
        if row['x'] < 0.15:
            assert abs(row['rho'] - 1.0) < 0.01, \
                f"At x={row['x']:.4f}, rho={row['rho']:.4f}, expected ~1.0"
            assert abs(row['u']) < 0.01, \
                f"At x={row['x']:.4f}, u={row['u']:.4f}, expected ~0.0"
            break


def test_undisturbed_right_state():
    """Density in undisturbed right region (x > 0.95) must be ~0.125."""
    rows = load_solution_csv()
    for row in reversed(rows):
        if row['x'] > 0.95:
            assert abs(row['rho'] - 0.125) < 0.01, \
                f"At x={row['x']:.4f}, rho={row['rho']:.4f}, expected ~0.125"
            assert abs(row['u']) < 0.01, \
                f"At x={row['x']:.4f}, u={row['u']:.4f}, expected ~0.0"
            break


def test_positive_density_and_pressure():
    """All density and pressure values must be strictly positive."""
    rows = load_solution_csv()
    for row in rows:
        assert row['rho'] > 0, f"Non-positive density at x={row['x']}"
        assert row['p'] > 0, f"Non-positive pressure at x={row['x']}"


# ---------- Independent L2 verification ----------

def test_independent_l2_error():
    """
    Independently compute L2 error against exact Riemann solution using
    hardcoded exact star-state values, not trusting the agent's computation.
    """
    rows = load_solution_csv()
    N = len(rows)
    assert N == 400

    gamma = 1.4
    gm1 = gamma - 1.0
    gp1 = gamma + 1.0
    t = 0.2
    x0 = 0.5
    dx = 1.0 / N

    rho_L, u_L, p_L = 1.0, 0.0, 1.0
    rho_R, u_R, p_R = 0.125, 0.0, 0.1
    a_L = math.sqrt(gamma * p_L / rho_L)

    p_star = 0.30313
    u_star = 0.92745
    rho_star_L = rho_L * (p_star / p_L) ** (1.0 / gamma)
    a_star_L = math.sqrt(gamma * p_star / rho_star_L)
    rho_star_R = rho_R * (
        (p_star / p_R + gm1 / gp1) / (gm1 / gp1 * p_star / p_R + 1.0)
    )
    a_R = math.sqrt(gamma * p_R / rho_R)
    S_shock = u_R + a_R * math.sqrt(gp1 / (2 * gamma) * p_star / p_R + gm1 / (2 * gamma))

    l2_sum = 0.0
    for row in rows:
        xi = (row['x'] - x0) / t

        if xi < u_L - a_L:
            rho_exact = rho_L
        elif xi < u_star - a_star_L:
            coeff = 2.0 / gp1 + gm1 / (gp1 * a_L) * (u_L - xi)
            rho_exact = rho_L * coeff ** (2.0 / gm1)
        elif xi < u_star:
            rho_exact = rho_star_L
        elif xi < S_shock:
            rho_exact = rho_star_R
        else:
            rho_exact = rho_R

        l2_sum += (row['rho'] - rho_exact) ** 2

    l2_error = math.sqrt(dx * l2_sum)
    assert l2_error < 0.05, \
        f"Independent L2 error {l2_error:.6f} exceeds threshold 0.05"


def test_monotonicity_in_plateau():
    """
    In the star-left plateau region, density should be approximately constant
    (not oscillating wildly), confirming the limiter is working.
    """
    rows = load_solution_csv()
    plateau_rho = [r['rho'] for r in rows if 0.50 < r['x'] < 0.66]
    if len(plateau_rho) < 5:
        pytest.skip("Not enough points in plateau region")

    rho_std = (sum((r - sum(plateau_rho) / len(plateau_rho)) ** 2
                   for r in plateau_rho) / len(plateau_rho)) ** 0.5
    mean_rho = sum(plateau_rho) / len(plateau_rho)

    # Coefficient of variation should be small (< 5%)
    assert rho_std / mean_rho < 0.05, \
        f"Density oscillations in star-left plateau: CV = {rho_std/mean_rho:.4f}"
