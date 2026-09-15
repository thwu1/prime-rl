
import pytest
import json
import csv
import os
import sys
import numpy as np

# ---------------------------------------------------------------------------
# Reference implementation for verification (compact independent solver)
# ---------------------------------------------------------------------------

class _RefRiemann:
    """Minimal independent implementation for test verification."""

    def __init__(self, gamma):
        self.g = gamma
        self.gm1 = gamma - 1.0
        self.gp1 = gamma + 1.0
        self.g1 = self.gm1 / (2.0 * gamma)
        self.g2 = self.gp1 / (2.0 * gamma)
        self.g3 = self.gm1 / self.gp1

    def _fk(self, p, rho_k, p_k, a_k):
        if p > p_k:
            A = 2.0 / (self.gp1 * rho_k)
            B = self.g3 * p_k
            return (p - p_k) * np.sqrt(A / (p + B))
        else:
            return (2.0 * a_k / self.gm1) * ((p / p_k) ** self.g1 - 1.0)

    def _dfk(self, p, rho_k, p_k, a_k):
        if p > p_k:
            A = 2.0 / (self.gp1 * rho_k)
            B = self.g3 * p_k
            return np.sqrt(A / (p + B)) * (1.0 - (p - p_k) / (2.0 * (p + B)))
        else:
            return (1.0 / (rho_k * a_k)) * (p / p_k) ** (-(self.gp1) / (2.0 * self.g))

    def solve(self, rhoL, uL, pL, rhoR, uR, pR):
        aL = np.sqrt(self.g * pL / rhoL)
        aR = np.sqrt(self.g * pR / rhoR)
        p = max(1e-15, 0.5 * (pL + pR) - 0.125 * (uR - uL) * (rhoL + rhoR) * (aL + aR))
        for _ in range(300):
            f = self._fk(p, rhoL, pL, aL) + self._fk(p, rhoR, pR, aR) + (uR - uL)
            df = self._dfk(p, rhoL, pL, aL) + self._dfk(p, rhoR, pR, aR)
            if abs(df) < 1e-30:
                break
            dp = -f / df
            p = max(1e-15, p + dp)
            if abs(dp) < 1e-14 * max(1.0, p):
                break
        u = 0.5 * (uL + uR) + 0.5 * (self._fk(p, rhoR, pR, aR) - self._fk(p, rhoL, pL, aL))
        if p > pL:
            rho_sL = rhoL * ((p / pL + self.g3) / (self.g3 * p / pL + 1.0))
        else:
            rho_sL = rhoL * (p / pL) ** (1.0 / self.g)
        if p > pR:
            rho_sR = rhoR * ((p / pR + self.g3) / (self.g3 * p / pR + 1.0))
        else:
            rho_sR = rhoR * (p / pR) ** (1.0 / self.g)
        return p, u, rho_sL, rho_sR

    def sample(self, x, t, x0, rhoL, uL, pL, rhoR, uR, pR):
        ps, us, rsL, rsR = self.solve(rhoL, uL, pL, rhoR, uR, pR)
        aL = np.sqrt(self.g * pL / rhoL)
        aR = np.sqrt(self.g * pR / rhoR)
        xi = (x - x0) / t
        # Left wave
        if ps <= pL:
            asL = aL * (ps / pL) ** self.g1
            hL = uL - aL
            tL = us - asL
            if xi <= hL:
                return rhoL, uL, pL
            elif xi <= tL:
                u = (2.0 / self.gp1) * (aL + self.gm1 / 2.0 * uL + xi)
                a = (2.0 / self.gp1) * (aL + self.gm1 / 2.0 * (uL - xi))
                rho = rhoL * (a / aL) ** (2.0 / self.gm1)
                p = pL * (a / aL) ** (2.0 * self.g / self.gm1)
                return float(rho), float(u), float(p)
            elif xi <= us:
                return rsL, us, ps
        else:
            SL = uL - aL * np.sqrt(self.g2 * ps / pL + self.g1)
            if xi <= SL:
                return rhoL, uL, pL
            elif xi <= us:
                return rsL, us, ps
        # Right wave
        if ps <= pR:
            asR = aR * (ps / pR) ** self.g1
            hR = uR + aR
            tR = us + asR
            if xi >= hR:
                return rhoR, uR, pR
            elif xi >= tR:
                u = (2.0 / self.gp1) * (-aR + self.gm1 / 2.0 * uR + xi)
                a = (2.0 / self.gp1) * (aR - self.gm1 / 2.0 * (uR - xi))
                rho = rhoR * (a / aR) ** (2.0 / self.gm1)
                p = pR * (a / aR) ** (2.0 * self.g / self.gm1)
                return float(rho), float(u), float(p)
            else:
                return rsR, us, ps
        else:
            SR = uR + aR * np.sqrt(self.g2 * ps / pR + self.g1)
            if xi >= SR:
                return rhoR, uR, pR
            else:
                return rsR, us, ps


# ---------------------------------------------------------------------------
# Problem parameters (from the case files)
# ---------------------------------------------------------------------------
LAX_RHOL, LAX_UL, LAX_PL = 0.445, 0.698, 3.528
LAX_RHOR, LAX_UR, LAX_PR = 0.5, 0.0, 0.571
LAX_GAMMA = 1.4
LAX_XLEFT, LAX_XRIGHT = -5.0, 5.0
LAX_X0 = 0.0
LAX_TEND = 1.3


# ===========================================================================
# Tests
# ===========================================================================

class TestRiemannModule:
    """Verify that the agent's solver module is a correct general-purpose implementation."""

    @pytest.fixture(autouse=True)
    def _import_riemann(self):
        sys.path.insert(0, "/app")
        import importlib
        self.riemann = importlib.import_module("riemann")

    def test_module_has_solve(self):
        assert hasattr(self.riemann, "solve"), "riemann.py must expose a 'solve' function"

    def test_module_has_sample(self):
        assert hasattr(self.riemann, "sample"), "riemann.py must expose a 'sample' function"

    # --- Sod problem (known reference values from Toro) ---
    def test_sod_star_pressure(self):
        sol = self.riemann.solve(1.0, 0.0, 1.0, 0.125, 0.0, 0.1, 1.4)
        assert abs(sol["p_star"] - 0.30313) < 1e-3, f"Sod p*={sol['p_star']}, expected ~0.30313"

    def test_sod_star_velocity(self):
        sol = self.riemann.solve(1.0, 0.0, 1.0, 0.125, 0.0, 0.1, 1.4)
        assert abs(sol["u_star"] - 0.92745) < 1e-3, f"Sod u*={sol['u_star']}, expected ~0.92745"

    def test_sod_star_densities(self):
        sol = self.riemann.solve(1.0, 0.0, 1.0, 0.125, 0.0, 0.1, 1.4)
        assert abs(sol["rho_star_L"] - 0.42632) < 1e-3, f"Sod rho*L={sol['rho_star_L']}"
        assert abs(sol["rho_star_R"] - 0.26557) < 1e-3, f"Sod rho*R={sol['rho_star_R']}"

    def test_sod_sampling_undisturbed(self):
        """Sample in undisturbed regions of Sod problem at t=0.2, domain [0,1], x0=0.5."""
        rho, u, p = self.riemann.sample(0.1, 0.2, 0.5, 1.0, 0.0, 1.0, 0.125, 0.0, 0.1, 1.4)
        assert abs(rho - 1.0) < 1e-6, "Should be undisturbed left state"
        assert abs(u - 0.0) < 1e-6
        assert abs(p - 1.0) < 1e-6
        rho, u, p = self.riemann.sample(0.95, 0.2, 0.5, 1.0, 0.0, 1.0, 0.125, 0.0, 0.1, 1.4)
        assert abs(rho - 0.125) < 1e-6, "Should be undisturbed right state"

    # --- Problem from case files (verified against reference) ---
    def test_lax_star_region(self):
        ref = _RefRiemann(LAX_GAMMA)
        ps_ref, us_ref, rsL_ref, rsR_ref = ref.solve(LAX_RHOL, LAX_UL, LAX_PL,
                                                       LAX_RHOR, LAX_UR, LAX_PR)
        sol = self.riemann.solve(LAX_RHOL, LAX_UL, LAX_PL,
                                 LAX_RHOR, LAX_UR, LAX_PR, LAX_GAMMA)
        assert abs(sol["p_star"] - ps_ref) < 1e-3, f"p*={sol['p_star']}, ref={ps_ref}"
        assert abs(sol["u_star"] - us_ref) < 1e-3, f"u*={sol['u_star']}, ref={us_ref}"
        assert abs(sol["rho_star_L"] - rsL_ref) < 1e-3
        assert abs(sol["rho_star_R"] - rsR_ref) < 1e-3

    def test_lax_sampling_multiple_points(self):
        """Verify sampling at several points across the problem domain."""
        ref = _RefRiemann(LAX_GAMMA)
        test_points = [-4.0, -3.0, -1.0, 0.0, 1.0, 2.0, 3.0, 4.0]
        for x in test_points:
            rho_ref, u_ref, p_ref = ref.sample(x, LAX_TEND, LAX_X0,
                                                LAX_RHOL, LAX_UL, LAX_PL,
                                                LAX_RHOR, LAX_UR, LAX_PR)
            rho, u, p = self.riemann.sample(x, LAX_TEND, LAX_X0,
                                             LAX_RHOL, LAX_UL, LAX_PL,
                                             LAX_RHOR, LAX_UR, LAX_PR, LAX_GAMMA)
            assert abs(rho - rho_ref) < 1e-4, f"rho mismatch at x={x}: {rho} vs {rho_ref}"
            assert abs(u - u_ref) < 1e-4, f"u mismatch at x={x}: {u} vs {u_ref}"
            assert abs(p - p_ref) < 1e-4, f"p mismatch at x={x}: {p} vs {p_ref}"


class TestExactSolutionFile:
    """Verify the exact solution output file."""

    def test_file_exists(self):
        assert os.path.isfile("/app/results/exact_solution.csv"), "exact_solution.csv missing"

    def test_columns_and_rows(self):
        with open("/app/results/exact_solution.csv") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 1000, f"Expected 1000 rows, got {len(rows)}"
        for col in ["x", "rho", "u", "p", "e"]:
            assert col in rows[0], f"Missing column '{col}'"

    def test_boundary_values(self):
        """First and last points should be undisturbed left/right states."""
        with open("/app/results/exact_solution.csv") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        first = rows[0]
        assert abs(float(first["rho"]) - LAX_RHOL) < 1e-4, "First row should be left state"
        assert abs(float(first["p"]) - LAX_PL) < 1e-4
        last = rows[-1]
        assert abs(float(last["rho"]) - LAX_RHOR) < 1e-4, "Last row should be right state"
        assert abs(float(last["p"]) - LAX_PR) < 1e-4

    def test_internal_energy_consistency(self):
        """Check e = p / (rho * (gamma-1))."""
        with open("/app/results/exact_solution.csv") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        for row in rows[::100]:  # sample every 100th row
            rho = float(row["rho"])
            p = float(row["p"])
            e = float(row["e"])
            e_expected = p / (rho * (LAX_GAMMA - 1.0))
            assert abs(e - e_expected) < 1e-3, f"e inconsistency at x={row['x']}"

    def test_midpoint_values(self):
        """Check a mid-domain point against reference implementation."""
        ref = _RefRiemann(LAX_GAMMA)
        with open("/app/results/exact_solution.csv") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        # Row 500 is near x=0 (center of domain)
        row = rows[500]
        x = float(row["x"])
        rho_ref, u_ref, p_ref = ref.sample(x, LAX_TEND, LAX_X0,
                                             LAX_RHOL, LAX_UL, LAX_PL,
                                             LAX_RHOR, LAX_UR, LAX_PR)
        assert abs(float(row["rho"]) - rho_ref) < 1e-3, f"rho mismatch at x={x}"
        assert abs(float(row["u"]) - u_ref) < 1e-3, f"u mismatch at x={x}"
        assert abs(float(row["p"]) - p_ref) < 1e-3, f"p mismatch at x={x}"


class TestWaveStructure:
    """Verify wave structure analysis."""

    @pytest.fixture(autouse=True)
    def _load_wave(self):
        with open("/app/results/wave_structure.json") as f:
            self.ws = json.load(f)

    def test_left_wave_type(self):
        assert self.ws["left_wave"]["type"] == "rarefaction", \
            f"Left wave should be rarefaction, got {self.ws['left_wave']['type']}"

    def test_right_wave_type(self):
        assert self.ws["right_wave"]["type"] == "shock", \
            f"Right wave should be shock, got {self.ws['right_wave']['type']}"

    def test_left_rarefaction_speeds(self):
        ref = _RefRiemann(LAX_GAMMA)
        ps, us, rsL, rsR = ref.solve(LAX_RHOL, LAX_UL, LAX_PL,
                                       LAX_RHOR, LAX_UR, LAX_PR)
        aL = np.sqrt(LAX_GAMMA * LAX_PL / LAX_RHOL)
        head_ref = LAX_UL - aL
        asL = aL * (ps / LAX_PL) ** ((LAX_GAMMA - 1) / (2 * LAX_GAMMA))
        tail_ref = us - asL
        assert abs(self.ws["left_wave"]["head_speed"] - head_ref) < 1e-2
        assert abs(self.ws["left_wave"]["tail_speed"] - tail_ref) < 1e-2

    def test_contact_speed(self):
        ref = _RefRiemann(LAX_GAMMA)
        ps, us, _, _ = ref.solve(LAX_RHOL, LAX_UL, LAX_PL,
                                  LAX_RHOR, LAX_UR, LAX_PR)
        assert abs(self.ws["contact"]["speed"] - us) < 1e-2

    def test_right_shock_speed(self):
        ref = _RefRiemann(LAX_GAMMA)
        ps, us, _, _ = ref.solve(LAX_RHOL, LAX_UL, LAX_PL,
                                  LAX_RHOR, LAX_UR, LAX_PR)
        aR = np.sqrt(LAX_GAMMA * LAX_PR / LAX_RHOR)
        SR = LAX_UR + aR * np.sqrt((LAX_GAMMA + 1) / (2 * LAX_GAMMA) * ps / LAX_PR +
                                    (LAX_GAMMA - 1) / (2 * LAX_GAMMA))
        assert abs(self.ws["right_wave"]["speed"] - SR) < 1e-2

    def test_star_region_values(self):
        ref = _RefRiemann(LAX_GAMMA)
        ps, us, rsL, rsR = ref.solve(LAX_RHOL, LAX_UL, LAX_PL,
                                       LAX_RHOR, LAX_UR, LAX_PR)
        sr = self.ws["star_region"]
        assert abs(sr["pressure"] - ps) < 1e-2
        assert abs(sr["velocity"] - us) < 1e-2
        assert abs(sr["density_left"] - rsL) < 1e-2
        assert abs(sr["density_right"] - rsR) < 1e-2


class TestNumericalSolutions:
    """Verify numerical solution files."""

    def test_numerical_files_exist(self):
        for n in [100, 200, 400]:
            path = f"/app/results/numerical_{n}.csv"
            assert os.path.isfile(path), f"{path} missing"

    def test_numerical_file_format(self):
        for n in [100, 200, 400]:
            with open(f"/app/results/numerical_{n}.csv") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            assert len(rows) == n, f"numerical_{n}.csv should have {n} rows, got {len(rows)}"
            for col in ["x", "rho", "u", "p"]:
                assert col in rows[0], f"Missing column '{col}' in numerical_{n}.csv"

    def test_numerical_physical_bounds(self):
        """Density and pressure must be positive everywhere."""
        for n in [100, 200, 400]:
            with open(f"/app/results/numerical_{n}.csv") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    rho = float(row["rho"])
                    p = float(row["p"])
                    assert rho > 0, f"Negative density in numerical_{n}.csv at x={row['x']}"
                    assert p > 0, f"Negative pressure in numerical_{n}.csv at x={row['x']}"


class TestConvergence:
    """Verify mesh convergence behavior."""

    @pytest.fixture(autouse=True)
    def _load_convergence(self):
        with open("/app/results/convergence.json") as f:
            self.conv = json.load(f)

    def test_convergence_structure(self):
        assert "L1_errors" in self.conv
        assert "convergence_rates" in self.conv
        for var in ["rho", "u", "p"]:
            assert var in self.conv["L1_errors"]
            assert len(self.conv["L1_errors"][var]) == 3
            assert var in self.conv["convergence_rates"]

    def test_errors_decrease(self):
        """L1 errors must decrease monotonically with refinement."""
        for var in ["rho", "u", "p"]:
            errs = self.conv["L1_errors"][var]
            assert errs[0] > errs[1] > errs[2], \
                f"Errors for {var} not decreasing: {errs}"

    def test_convergence_rate_positive(self):
        """Convergence rate must be positive and physically reasonable (> 0.3)."""
        for var in ["rho", "u", "p"]:
            rate = self.conv["convergence_rates"][var]
            assert rate > 0.3, f"Convergence rate for {var} too low: {rate}"
            assert rate < 3.0, f"Convergence rate for {var} suspiciously high: {rate}"

    def test_errors_are_small(self):
        """Finest grid errors should be reasonably small."""
        for var in ["rho", "u", "p"]:
            finest_err = self.conv["L1_errors"][var][2]  # N=400
            assert finest_err < 1.0, f"L1 error for {var} at N=400 too large: {finest_err}"
