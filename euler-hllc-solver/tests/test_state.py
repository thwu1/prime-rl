"""
Tests for the multi-material 1D Euler HLLC solver task.
Includes an independent multi-gamma exact Riemann solver for verification.
"""

import pytest
import json
import csv
import os
import math

RESULTS_DIR = "/app/results"
CONFIG_FILE = "/app/config/problems.json"


def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)


def get_gamma_lr(prob):
    """Extract left/right gamma from a problem definition."""
    gL = prob.get("gamma_left", prob.get("gamma", 1.4))
    gR = prob.get("gamma_right", prob.get("gamma", 1.4))
    return gL, gR


def exact_riemann_multigamma(rhoL, uL, pL, gamL, rhoR, uR, pR, gamR,
                              x0, t, x_arr):
    """Exact Riemann solver supporting different gamma on each side.

    Returns list of (rho, u, p, E, gamma_local) tuples.
    """
    gm1L, gp1L = gamL - 1.0, gamL + 1.0
    g_ratL = gm1L / gp1L
    aL = math.sqrt(gamL * pL / rhoL)

    gm1R, gp1R = gamR - 1.0, gamR + 1.0
    g_ratR = gm1R / gp1R
    aR = math.sqrt(gamR * pR / rhoR)

    # Newton iteration for star-region pressure
    ppv = 0.5 * (pL + pR) - 0.125 * (uR - uL) * (rhoL + rhoR) * (aL + aR)
    p_star = max(ppv, 1e-10)

    for _ in range(300):
        # Left wave contribution (uses gamL)
        if p_star <= pL:
            ratio = p_star / pL
            pwr = gm1L / (2.0 * gamL)
            fL = (2.0 * aL / gm1L) * (ratio ** pwr - 1.0)
            dfL = (1.0 / (rhoL * aL)) * ratio ** (-gp1L / (2.0 * gamL))
        else:
            A = 2.0 / (gp1L * rhoL)
            B = g_ratL * pL
            sq = math.sqrt(A / (p_star + B))
            fL = (p_star - pL) * sq
            dfL = sq * (1.0 - (p_star - pL) / (2.0 * (p_star + B)))

        # Right wave contribution (uses gamR)
        if p_star <= pR:
            ratio = p_star / pR
            pwr = gm1R / (2.0 * gamR)
            fR = (2.0 * aR / gm1R) * (ratio ** pwr - 1.0)
            dfR = (1.0 / (rhoR * aR)) * ratio ** (-gp1R / (2.0 * gamR))
        else:
            A = 2.0 / (gp1R * rhoR)
            B = g_ratR * pR
            sq = math.sqrt(A / (p_star + B))
            fR = (p_star - pR) * sq
            dfR = sq * (1.0 - (p_star - pR) / (2.0 * (p_star + B)))

        f_val = fL + fR + (uR - uL)
        df_val = dfL + dfR
        if abs(df_val) < 1e-30:
            break
        p_new = max(p_star - f_val / df_val, 1e-10)
        if abs(p_new - p_star) / (0.5 * (p_new + p_star) + 1e-30) < 1e-12:
            p_star = p_new
            break
        p_star = p_new

    # Compute u*
    if p_star <= pL:
        fL_f = (2.0 * aL / gm1L) * ((p_star / pL) ** (gm1L / (2.0 * gamL)) - 1.0)
    else:
        A = 2.0 / (gp1L * rhoL)
        B = g_ratL * pL
        fL_f = (p_star - pL) * math.sqrt(A / (p_star + B))

    if p_star <= pR:
        fR_f = (2.0 * aR / gm1R) * ((p_star / pR) ** (gm1R / (2.0 * gamR)) - 1.0)
    else:
        A = 2.0 / (gp1R * rhoR)
        B = g_ratR * pR
        fR_f = (p_star - pR) * math.sqrt(A / (p_star + B))

    u_star = 0.5 * (uL + uR) + 0.5 * (fR_f - fL_f)

    results = []
    for x in x_arr:
        S = (x - x0) / t

        if S <= u_star:
            # Left of contact — use gamL
            gm1 = gm1L
            gp1 = gp1L
            g_rat = g_ratL
            gam = gamL
            a0 = aL
            rho0, u0, p0 = rhoL, uL, pL

            if p_star <= p0:
                a_s = a0 * (p_star / p0) ** (gm1 / (2.0 * gam))
                S_H = u0 - a0
                S_T = u_star - a_s
                if S <= S_H:
                    rho_s, u_s, p_s = rho0, u0, p0
                elif S <= S_T:
                    base = 2.0 / gp1 + gm1 / (gp1 * a0) * (u0 - S)
                    rho_s = rho0 * base ** (2.0 / gm1)
                    u_s = 2.0 / gp1 * (a0 + gm1 / 2.0 * u0 + S)
                    p_s = p0 * base ** (2.0 * gam / gm1)
                else:
                    rho_s = rho0 * (p_star / p0) ** (1.0 / gam)
                    u_s, p_s = u_star, p_star
            else:
                S_sh = u0 - a0 * math.sqrt(
                    gp1 / (2.0 * gam) * (p_star / p0)
                    + gm1 / (2.0 * gam))
                if S <= S_sh:
                    rho_s, u_s, p_s = rho0, u0, p0
                else:
                    rho_s = rho0 * ((p_star / p0 + g_rat)
                                    / (g_rat * p_star / p0 + 1.0))
                    u_s, p_s = u_star, p_star
        else:
            # Right of contact — use gamR
            gm1 = gm1R
            gp1 = gp1R
            g_rat = g_ratR
            gam = gamR
            a0 = aR
            rho0, u0, p0 = rhoR, uR, pR

            if p_star <= p0:
                a_s = a0 * (p_star / p0) ** (gm1 / (2.0 * gam))
                S_H = u0 + a0
                S_T = u_star + a_s
                if S >= S_H:
                    rho_s, u_s, p_s = rho0, u0, p0
                elif S >= S_T:
                    base = 2.0 / gp1 - gm1 / (gp1 * a0) * (u0 - S)
                    rho_s = rho0 * base ** (2.0 / gm1)
                    u_s = 2.0 / gp1 * (-a0 + gm1 / 2.0 * u0 + S)
                    p_s = p0 * base ** (2.0 * gam / gm1)
                else:
                    rho_s = rho0 * (p_star / p0) ** (1.0 / gam)
                    u_s, p_s = u_star, p_star
            else:
                S_sh = u0 + a0 * math.sqrt(
                    gp1 / (2.0 * gam) * (p_star / p0)
                    + gm1 / (2.0 * gam))
                if S >= S_sh:
                    rho_s, u_s, p_s = rho0, u0, p0
                else:
                    rho_s = rho0 * ((p_star / p0 + g_rat)
                                    / (g_rat * p_star / p0 + 1.0))
                    u_s, p_s = u_star, p_star

        E = p_s / ((gam - 1.0) * rho_s) + 0.5 * u_s ** 2
        results.append((rho_s, u_s, p_s, E, gam))

    return results


def read_csv_results(filename):
    """Read a results CSV file."""
    filepath = os.path.join(RESULTS_DIR, filename)
    data = {"x": [], "density": [], "velocity": [], "pressure": [],
            "energy": []}
    gamma_col = []
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            data["x"].append(float(row["x"]))
            data["density"].append(float(row["density"]))
            data["velocity"].append(float(row["velocity"]))
            data["pressure"].append(float(row["pressure"]))
            data["energy"].append(float(row["energy"]))
            if "gamma" in row:
                gamma_col.append(float(row["gamma"]))
    data["gamma"] = gamma_col
    return data


def compute_l1_error(numerical, exact_vals):
    n = len(numerical)
    assert n == len(exact_vals)
    return sum(abs(numerical[i] - exact_vals[i]) for i in range(n)) / n


def get_exact_for_problem(name):
    """Compute exact solution for a named problem."""
    config = load_config()
    prob = config["problems"][name]
    ls, rs = prob["left_state"], prob["right_state"]
    gamL, gamR = get_gamma_lr(prob)

    data = read_csv_results(f"{name}.csv")
    exact = exact_riemann_multigamma(
        ls["density"], ls["velocity"], ls["pressure"], gamL,
        rs["density"], rs["velocity"], rs["pressure"], gamR,
        prob["diaphragm"], prob["t_final"], data["x"],
    )
    return data, exact


# =========================================================================
# Output file existence
# =========================================================================

class TestOutputFiles:
    def test_blast_csv_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "blast.csv"))

    def test_contact_csv_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "contact.csv"))

    def test_multigamma_csv_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "multigamma.csv"))

    def test_errors_json_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "errors.json"))

    def test_convergence_json_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "convergence.json"))


# =========================================================================
# CSV format
# =========================================================================

class TestCSVFormat:
    def test_blast_columns(self):
        with open(os.path.join(RESULTS_DIR, "blast.csv")) as f:
            reader = csv.DictReader(f)
            for col in ["x", "density", "velocity", "pressure", "energy"]:
                assert col in reader.fieldnames, f"Missing '{col}'"

    def test_blast_row_count(self):
        config = load_config()
        n = config["problems"]["blast"]["n_cells"]
        data = read_csv_results("blast.csv")
        assert len(data["x"]) == n

    def test_contact_row_count(self):
        config = load_config()
        n = config["problems"]["contact"]["n_cells"]
        data = read_csv_results("contact.csv")
        assert len(data["x"]) == n

    def test_multigamma_row_count(self):
        config = load_config()
        n = config["problems"]["multigamma"]["n_cells"]
        data = read_csv_results("multigamma.csv")
        assert len(data["x"]) == n

    def test_multigamma_has_gamma_column(self):
        with open(os.path.join(RESULTS_DIR, "multigamma.csv")) as f:
            reader = csv.DictReader(f)
            assert "gamma" in reader.fieldnames, \
                "multigamma.csv must have a 'gamma' column"


# =========================================================================
# Blast accuracy (custom non-textbook problem)
# =========================================================================

class TestBlastAccuracy:
    def test_blast_density_l1(self):
        data, exact = get_exact_for_problem("blast")
        exact_rho = [e[0] for e in exact]
        l1 = compute_l1_error(data["density"], exact_rho)
        assert l1 < 0.040, f"Blast density L1={l1:.6e} exceeds 0.040"

    def test_blast_pressure_l1(self):
        data, exact = get_exact_for_problem("blast")
        exact_p = [e[2] for e in exact]
        l1 = compute_l1_error(data["pressure"], exact_p)
        assert l1 < 0.060, f"Blast pressure L1={l1:.6e} exceeds 0.060"

    def test_blast_velocity_l1(self):
        data, exact = get_exact_for_problem("blast")
        exact_u = [e[1] for e in exact]
        l1 = compute_l1_error(data["velocity"], exact_u)
        assert l1 < 0.060, f"Blast velocity L1={l1:.6e} exceeds 0.060"

    def test_blast_undisturbed_left(self):
        data = read_csv_results("blast.csv")
        assert abs(data["density"][0] - 2.281) < 0.01
        assert abs(data["pressure"][0] - 5.917) < 0.01
        assert abs(data["velocity"][0]) < 0.01

    def test_blast_undisturbed_right(self):
        data = read_csv_results("blast.csv")
        assert abs(data["density"][-1] - 0.834) < 0.01
        assert abs(data["pressure"][-1] - 0.715) < 0.01
        assert abs(data["velocity"][-1]) < 0.01


# =========================================================================
# Contact accuracy (pure contact discontinuity)
# =========================================================================

class TestContactAccuracy:
    def test_contact_density_l1(self):
        data, exact = get_exact_for_problem("contact")
        exact_rho = [e[0] for e in exact]
        l1 = compute_l1_error(data["density"], exact_rho)
        assert l1 < 0.050, f"Contact density L1={l1:.6e} exceeds 0.050"

    def test_contact_uniform_pressure(self):
        """Pressure should remain ~1.0 everywhere for a pure contact."""
        data = read_csv_results("contact.csv")
        for i, pi in enumerate(data["pressure"]):
            assert abs(pi - 1.0) < 0.02, \
                f"Pressure deviation at x={data['x'][i]}: p={pi}"

    def test_contact_uniform_velocity(self):
        """Velocity should remain ~0.314 everywhere."""
        data = read_csv_results("contact.csv")
        for i, ui in enumerate(data["velocity"]):
            assert abs(ui - 0.314) < 0.02, \
                f"Velocity deviation at x={data['x'][i]}: u={ui}"

    def test_contact_no_negative_density(self):
        data = read_csv_results("contact.csv")
        for i, ri in enumerate(data["density"]):
            assert ri > 0, f"Negative density at x={data['x'][i]}"


# =========================================================================
# Multigamma accuracy (different gamma on each side — DNA test)
# =========================================================================

class TestMultigammaAccuracy:
    def test_multigamma_density_l1(self):
        data, exact = get_exact_for_problem("multigamma")
        exact_rho = [e[0] for e in exact]
        l1 = compute_l1_error(data["density"], exact_rho)
        assert l1 < 0.050, f"Multigamma density L1={l1:.6e} exceeds 0.050"

    def test_multigamma_pressure_l1(self):
        data, exact = get_exact_for_problem("multigamma")
        exact_p = [e[2] for e in exact]
        l1 = compute_l1_error(data["pressure"], exact_p)
        assert l1 < 0.060, f"Multigamma pressure L1={l1:.6e} exceeds 0.060"

    def test_multigamma_no_negative_density(self):
        data = read_csv_results("multigamma.csv")
        for i, ri in enumerate(data["density"]):
            assert ri > 0, f"Negative density at x={data['x'][i]}"

    def test_multigamma_no_negative_pressure(self):
        data = read_csv_results("multigamma.csv")
        for i, pi in enumerate(data["pressure"]):
            assert pi > 0, f"Negative pressure at x={data['x'][i]}"

    def test_multigamma_gamma_left_region(self):
        """Cells far left of contact must have gamma ~ 1.4."""
        config = load_config()
        prob = config["problems"]["multigamma"]
        gamL, gamR = get_gamma_lr(prob)
        data = read_csv_results("multigamma.csv")
        assert len(data["gamma"]) == len(data["x"]), \
            "gamma column length mismatch"
        # Check first 20% of cells
        n_check = len(data["x"]) // 5
        for i in range(n_check):
            assert abs(data["gamma"][i] - gamL) < 0.05, \
                f"gamma[{i}]={data['gamma'][i]}, expected ~{gamL}"

    def test_multigamma_gamma_right_region(self):
        """Cells far right of contact must have gamma ~ 1.6667."""
        config = load_config()
        prob = config["problems"]["multigamma"]
        gamL, gamR = get_gamma_lr(prob)
        data = read_csv_results("multigamma.csv")
        n = len(data["x"])
        n_check = n // 5
        for i in range(n - n_check, n):
            assert abs(data["gamma"][i] - gamR) < 0.05, \
                f"gamma[{i}]={data['gamma'][i]}, expected ~{gamR}"

    def test_multigamma_undisturbed_left(self):
        data = read_csv_results("multigamma.csv")
        assert abs(data["density"][0] - 1.137) < 0.01
        assert abs(data["pressure"][0] - 3.059) < 0.01

    def test_multigamma_undisturbed_right(self):
        data = read_csv_results("multigamma.csv")
        assert abs(data["density"][-1] - 0.683) < 0.01
        assert abs(data["pressure"][-1] - 0.427) < 0.01


# =========================================================================
# Energy thermodynamic consistency
# =========================================================================

class TestEnergyConsistency:
    @pytest.mark.parametrize("name", ["blast", "contact"])
    def test_energy_single_gamma(self, name):
        """Verify E = p/(rho*(gamma-1)) + 0.5*u^2 for single-gamma."""
        config = load_config()
        gamma = config["problems"][name]["gamma"]
        gm1 = gamma - 1.0
        data = read_csv_results(f"{name}.csv")
        for i in range(len(data["x"])):
            expected = (data["pressure"][i]
                        / (gm1 * data["density"][i])
                        + 0.5 * data["velocity"][i] ** 2)
            rel = abs(data["energy"][i] - expected) / (abs(expected) + 1e-30)
            assert rel < 0.01, \
                f"{name} energy mismatch at x={data['x'][i]}"

    def test_energy_multigamma(self):
        """Verify E = p/(rho*(gamma_local-1)) + 0.5*u^2 for multigamma."""
        data = read_csv_results("multigamma.csv")
        assert len(data["gamma"]) == len(data["x"])
        for i in range(len(data["x"])):
            gm1 = data["gamma"][i] - 1.0
            expected = (data["pressure"][i]
                        / (gm1 * data["density"][i])
                        + 0.5 * data["velocity"][i] ** 2)
            rel = abs(data["energy"][i] - expected) / (abs(expected) + 1e-30)
            assert rel < 0.01, \
                f"multigamma energy mismatch at x={data['x'][i]}"


# =========================================================================
# Convergence study
# =========================================================================

class TestConvergence:
    def test_convergence_resolutions_match(self):
        with open(os.path.join(RESULTS_DIR, "convergence.json")) as f:
            conv = json.load(f)
        config = load_config()
        expected = config["convergence"]["resolutions"]
        assert conv["resolutions"] == expected

    def test_convergence_errors_decrease(self):
        with open(os.path.join(RESULTS_DIR, "convergence.json")) as f:
            conv = json.load(f)
        errors = conv["errors"]
        for i in range(len(errors) - 1):
            assert errors[i + 1] < errors[i], \
                f"Errors not decreasing: e[{i}]={errors[i]}, e[{i+1}]={errors[i+1]}"

    def test_convergence_rate_range(self):
        with open(os.path.join(RESULTS_DIR, "convergence.json")) as f:
            conv = json.load(f)
        rate = conv["rate"]
        assert 0.4 <= rate <= 1.3, \
            f"Convergence rate {rate} outside [0.4, 1.3]"

    def test_finest_resolution_error(self):
        with open(os.path.join(RESULTS_DIR, "convergence.json")) as f:
            conv = json.load(f)
        finest = conv["errors"][-1]
        assert finest < 0.012, \
            f"Finest-grid error {finest} too large (expected < 0.012)"


# =========================================================================
# errors.json validity
# =========================================================================

class TestErrorsFile:
    def test_errors_json_keys(self):
        with open(os.path.join(RESULTS_DIR, "errors.json")) as f:
            data = json.load(f)
        for key in ["blast", "contact", "multigamma"]:
            assert key in data, f"Missing key '{key}'"

    def test_errors_positive(self):
        with open(os.path.join(RESULTS_DIR, "errors.json")) as f:
            data = json.load(f)
        for key in ["blast", "contact", "multigamma"]:
            assert data[key] > 0, f"Error for {key} must be positive"

    def test_errors_consistent_with_convergence(self):
        """Blast error at N=500 in errors.json should match convergence."""
        with open(os.path.join(RESULTS_DIR, "errors.json")) as f:
            errors = json.load(f)
        with open(os.path.join(RESULTS_DIR, "convergence.json")) as f:
            conv = json.load(f)
        config = load_config()
        blast_n = config["problems"]["blast"]["n_cells"]
        if blast_n in conv["resolutions"]:
            idx = conv["resolutions"].index(blast_n)
            conv_err = conv["errors"][idx]
            rel = abs(errors["blast"] - conv_err) / (conv_err + 1e-30)
            assert rel < 0.05, \
                f"errors.json blast={errors['blast']:.6e} " \
                f"vs convergence={conv_err:.6e}"
