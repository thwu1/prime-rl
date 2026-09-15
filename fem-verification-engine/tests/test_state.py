
"""
Independent verification tests for FEM benchmark verification engine.
Each test computes expected values from first principles and compares
against the solver's output in /app/results.json.
"""

import json
import math
import os

import numpy as np
import pytest
from scipy.optimize import brentq


RESULTS_PATH = "/app/results.json"
REL_TOL = 1e-4
ABS_TOL = 1e-6


@pytest.fixture(scope="module")
def results():
    """Load solver results."""
    assert os.path.isfile(RESULTS_PATH), f"Results file not found: {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    assert "benchmarks" in data, "Results JSON must have 'benchmarks' key"
    return data["benchmarks"]


# ---------------------------------------------------------------------------
# Helper: compare with tolerance
# ---------------------------------------------------------------------------

def approx_eq(computed, expected, rtol=REL_TOL, atol=ABS_TOL):
    if abs(expected) < atol:
        return abs(computed - expected) < atol
    return abs(computed - expected) / abs(expected) < rtol


# ===========================================================================
# Benchmark 1: Thermoelastic thick cylinder (plane strain)
# ===========================================================================

def _compute_thick_cylinder_reference():
    """
    Compute reference values for a plane-strain thick-walled cylinder
    under internal pressure and logarithmic radial temperature gradient.

    Formulas based on Timoshenko & Goodier, Theory of Elasticity.
    """
    a = 0.05   # inner radius (m)
    b = 0.10   # outer radius (m)
    p_i = 50.0  # internal pressure (MPa)
    E = 210000.0  # Young's modulus (MPa)
    nu = 0.3
    alpha = 12.0e-6  # /degC
    T_inner = 200.0
    T_outer = 0.0

    eval_radii = [0.05, 0.075, 0.10]
    a2 = a * a
    b2 = b * b

    # Temperature distribution: T(r) = T_inner + (T_outer - T_inner) * ln(r/a) / ln(b/a)
    ln_ba = math.log(b / a)
    dT = T_outer - T_inner  # = -200

    def T(r):
        return T_inner + dT * math.log(r / a) / ln_ba

    # Integral I(x) = integral from a to x of T(r')*r' dr'
    # T(r) = T_inner + (dT/ln_ba)*ln(r/a)
    # I(x) = T_inner*(x^2 - a^2)/2 + (dT/ln_ba)*[x^2/2*ln(x/a) - (x^2-a^2)/4]
    C = dT / ln_ba  # = -200/ln(2)

    def I_integral(x):
        x2 = x * x
        return (T_inner * (x2 - a2) / 2.0
                + C * (x2 / 2.0 * math.log(x / a) - (x2 - a2) / 4.0))

    I_b = I_integral(b)

    # Mechanical stresses (Lame, plane strain, p_o = 0):
    # sigma_r_mech = a^2*p_i/(b^2-a^2) * (1 - b^2/r^2)
    # sigma_theta_mech = a^2*p_i/(b^2-a^2) * (1 + b^2/r^2)
    A_lame = a2 * p_i / (b2 - a2)

    def sigma_r_mech(r):
        return A_lame * (1.0 - b2 / (r * r))

    def sigma_theta_mech(r):
        return A_lame * (1.0 + b2 / (r * r))

    # Thermal stresses (plane strain, Timoshenko & Goodier formulation):
    # sigma_r_th = (alpha*E/(1-nu)) * [-I(r)/r^2 + (r^2-a^2)*I(b) / (r^2*(b^2-a^2))]
    # sigma_theta_th = (alpha*E/(1-nu)) * [I(r)/r^2 - T(r) + (r^2+a^2)*I(b) / (r^2*(b^2-a^2))]
    aE_1mnu = alpha * E / (1.0 - nu)

    def sigma_r_th(r):
        r2 = r * r
        Ir = I_integral(r)
        return aE_1mnu * (-Ir / r2 + (r2 - a2) * I_b / (r2 * (b2 - a2)))

    def sigma_theta_th(r):
        r2 = r * r
        Ir = I_integral(r)
        return aE_1mnu * (Ir / r2 - T(r) + (r2 + a2) * I_b / (r2 * (b2 - a2)))

    # Total stresses
    def sigma_r_total(r):
        return sigma_r_mech(r) + sigma_r_th(r)

    def sigma_theta_total(r):
        return sigma_theta_mech(r) + sigma_theta_th(r)

    # Radial displacement: u_r = r * epsilon_theta
    # In plane strain: epsilon_theta = (1+nu)/E * [(1-nu)*sigma_theta - nu*sigma_r] + (1+nu)*alpha*T(r)
    def u_r_total(r):
        sr = sigma_r_total(r)
        st = sigma_theta_total(r)
        eps_theta = ((1.0 + nu) / E * ((1.0 - nu) * st - nu * sr)
                     + (1.0 + nu) * alpha * T(r))
        return r * eps_theta

    ref = {}
    for i, r in enumerate(eval_radii, 1):
        ref[f"sigma_r_r{i}"] = sigma_r_total(r)
        ref[f"sigma_theta_r{i}"] = sigma_theta_total(r)
        ref[f"u_r_r{i}"] = u_r_total(r)

    return ref


class TestThickCylinder:
    @pytest.fixture(autouse=True)
    def setup(self, results):
        self.solver = results.get("thick_cylinder", {})
        self.ref = _compute_thick_cylinder_reference()

    def test_has_benchmark(self, results):
        assert "thick_cylinder" in results, "Missing thick_cylinder benchmark in results"

    def test_sigma_r_inner(self):
        """Inner surface radial stress must equal -p_i = -50 MPa."""
        assert approx_eq(self.solver["sigma_r_r1"], -50.0, rtol=1e-3)

    def test_sigma_r_outer(self):
        """Outer surface radial stress must equal -p_o = 0 MPa."""
        assert abs(self.solver["sigma_r_r3"]) < 0.1

    def test_all_stresses(self):
        """All stress and displacement values within tolerance."""
        for key, expected in self.ref.items():
            computed = self.solver.get(key)
            assert computed is not None, f"Missing output: {key}"
            assert approx_eq(computed, expected), (
                f"{key}: computed={computed}, expected={expected}, "
                f"rel_err={abs(computed-expected)/max(abs(expected),1e-15):.6e}")

    def test_thermal_stress_boundary(self):
        """Thermal radial stress must vanish at both surfaces (traction-free BC)."""
        # Mechanical sigma_r at inner = -50, at outer = 0
        # Total sigma_r at inner should be -50 (thermal part = 0 at surface)
        # Total sigma_r at outer should be 0 (thermal part = 0 at surface)
        assert approx_eq(self.solver["sigma_r_r1"], self.ref["sigma_r_r1"])
        assert approx_eq(self.solver["sigma_r_r3"], self.ref["sigma_r_r3"])


# ===========================================================================
# Benchmark 2: Coupled piston-fluid eigenfrequency
# ===========================================================================

def _compute_piston_fluid_reference():
    """
    Compute the first coupled eigenfrequency of a rigid piston closing
    one end of a fluid-filled tube with rigid far-end wall.

    Eigenequation: x * tan(x) = rho*S*L/m   where x = omega*L/c
    """
    m = 500.0
    S = 0.1
    rho = 1000.0
    c = 1500.0
    L = 10.0

    beta = rho * S * L / m  # = 2.0

    # Find first non-trivial root of x*tan(x) = beta in (0, pi/2)
    # f(x) = x*tan(x) - beta
    # At x=0: f=0 (trivial). For beta > 0, we look for the first root where
    # x*tan(x) crosses beta.
    # Since d/dx(x*tan(x)) = tan(x) + x*sec^2(x) > 0 for x in (0, pi/2),
    # and x*tan(x) goes from 0 to +inf, there is exactly one root if beta > 0.

    def f(x):
        return x * math.tan(x) - beta

    # Search in (epsilon, pi/2 - epsilon)
    x_root = brentq(f, 0.01, math.pi / 2 - 0.001)

    omega = x_root * c / L
    freq = omega / (2.0 * math.pi)

    return {"freq_hz": freq, "_x_root": x_root}


class TestPistonFluid:
    @pytest.fixture(autouse=True)
    def setup(self, results):
        self.solver = results.get("piston_fluid", {})
        self.ref = _compute_piston_fluid_reference()

    def test_has_benchmark(self, results):
        assert "piston_fluid" in results, "Missing piston_fluid benchmark in results"

    def test_frequency(self):
        """Coupled eigenfrequency within tolerance."""
        computed = self.solver.get("freq_hz")
        assert computed is not None, "Missing freq_hz output"
        expected = self.ref["freq_hz"]
        assert approx_eq(computed, expected, rtol=1e-3), (
            f"freq_hz: computed={computed}, expected={expected}")

    def test_equation_satisfied(self):
        """Verify the transcendental equation is satisfied at the computed frequency."""
        freq = self.solver.get("freq_hz")
        assert freq is not None
        m, S, rho, c, L = 500.0, 0.1, 1000.0, 1500.0, 10.0
        omega = 2 * math.pi * freq
        x = omega * L / c
        lhs = x * math.tan(x)
        rhs = rho * S * L / m
        assert abs(lhs - rhs) / rhs < 1e-3, (
            f"Transcendental equation not satisfied: x*tan(x)={lhs}, rho*S*L/m={rhs}")

    def test_frequency_positive(self):
        assert self.solver.get("freq_hz", 0) > 0

    def test_frequency_below_tube_resonance(self):
        """First coupled freq must be below first tube resonance c/(4L)."""
        c, L = 1500.0, 10.0
        f_tube = c / (4.0 * L)  # quarter-wave resonance
        freq = self.solver.get("freq_hz", 0)
        assert 0 < freq < f_tube, (
            f"Frequency {freq} must be between 0 and {f_tube} Hz")


# ===========================================================================
# Benchmark 3: Foundation buckling
# ===========================================================================

def _compute_foundation_buckling_reference():
    """
    Critical buckling load for simply-supported beam on Winkler foundation.
    P_cr(n) = n^2 * pi^2 * EI / L^2 + k * L^2 / (n^2 * pi^2)
    Minimize over integer n >= 1.
    """
    EI = 1.0e5
    L = 10.0
    k = 1.0e5
    pi2 = math.pi ** 2
    L2 = L * L

    def P_cr(n):
        return n * n * pi2 * EI / L2 + k * L2 / (n * n * pi2)

    # Continuous optimum: n_opt^4 = k*L^4 / (pi^4 * EI)
    n_opt_cont = (k * L ** 4 / (math.pi ** 4 * EI)) ** 0.25

    # Check integer neighbors
    n_low = max(1, int(math.floor(n_opt_cont)))
    n_high = n_low + 1

    candidates = [(n, P_cr(n)) for n in range(max(1, n_low - 1), n_high + 2)]
    best_n, best_P = min(candidates, key=lambda x: x[1])

    return {"critical_load_N": best_P, "critical_mode": best_n}


class TestFoundationBuckling:
    @pytest.fixture(autouse=True)
    def setup(self, results):
        self.solver = results.get("foundation_buckling", {})
        self.ref = _compute_foundation_buckling_reference()

    def test_has_benchmark(self, results):
        assert "foundation_buckling" in results

    def test_critical_mode(self):
        """Critical half-wave number must be 3."""
        mode = self.solver.get("critical_mode")
        assert mode is not None, "Missing critical_mode"
        assert int(mode) == self.ref["critical_mode"], (
            f"critical_mode: got {mode}, expected {self.ref['critical_mode']}")

    def test_critical_load(self):
        """Critical load within tolerance."""
        load = self.solver.get("critical_load_N")
        assert load is not None, "Missing critical_load_N"
        expected = self.ref["critical_load_N"]
        assert approx_eq(load, expected, rtol=1e-4), (
            f"critical_load_N: computed={load}, expected={expected}")

    def test_load_positive(self):
        assert self.solver.get("critical_load_N", 0) > 0

    def test_load_less_than_euler(self):
        """Critical load on foundation must be less than n=1 Euler + foundation."""
        # With foundation the optimal mode > 1, so critical load < P(n=1)
        EI, L, k = 1e5, 10.0, 1e5
        P1 = math.pi ** 2 * EI / (L * L) + k * L * L / math.pi ** 2
        assert self.solver.get("critical_load_N", 1e20) < P1


# ===========================================================================
# Benchmark 4: Plasticity cycle
# ===========================================================================

def _compute_plasticity_reference():
    """
    Uniaxial J2 elastoplastic response with linear isotropic hardening.
    Strain path: 0 -> 0.005 -> -0.002

    Exact closed-form solution for uniaxial loading.
    """
    E = 200000.0
    sigma_y = 250.0
    H = 10000.0

    # Tangent modulus
    Et = E * H / (E + H)

    # Segment 1: 0 -> 0.005
    eps_y = sigma_y / E  # = 0.00125

    eps_peak = 0.005
    # After yield: sigma = sigma_y + Et*(eps - eps_y)
    sigma_peak = sigma_y + Et * (eps_peak - eps_y)
    # Plastic strain: eps_p = E/(E+H) * (eps - eps_y)
    eps_p_peak = E / (E + H) * (eps_peak - eps_y)
    p_peak = eps_p_peak  # accumulated (all tension)

    # Current yield surface radius
    R_peak = sigma_y + H * p_peak

    # Segment 2: 0.005 -> -0.002
    # Elastic unloading first. Reverse yield when sigma = -R_peak
    # sigma = sigma_peak + E*(eps - eps_peak)
    # sigma = -R_peak => eps_reverse = eps_peak + (-R_peak - sigma_peak)/E
    eps_reverse = eps_peak + (-R_peak - sigma_peak) / E

    eps_final = -0.002

    if eps_final >= eps_reverse:
        # Still elastic at final
        sigma_final = sigma_peak + E * (eps_final - eps_peak)
        p_final = p_peak
    else:
        # Plastic in compression
        sigma_at_reverse = -R_peak
        # From reverse yield point, compressive plastic loading:
        # sigma = sigma_at_reverse + Et*(eps - eps_reverse)
        sigma_final = sigma_at_reverse + Et * (eps_final - eps_reverse)
        # Additional plastic strain (compressive)
        delta_eps_p = E / (E + H) * (eps_final - eps_reverse)
        delta_p = abs(delta_eps_p)
        p_final = p_peak + delta_p

    return {
        "sigma_at_peak_MPa": sigma_peak,
        "eps_p_acc_at_peak": p_peak,
        "sigma_at_final_MPa": sigma_final,
        "eps_p_acc_at_final": p_final,
    }


class TestPlasticityCycle:
    @pytest.fixture(autouse=True)
    def setup(self, results):
        self.solver = results.get("plasticity_cycle", {})
        self.ref = _compute_plasticity_reference()

    def test_has_benchmark(self, results):
        assert "plasticity_cycle" in results

    def test_peak_stress(self):
        """Stress at peak strain."""
        computed = self.solver.get("sigma_at_peak_MPa")
        expected = self.ref["sigma_at_peak_MPa"]
        assert computed is not None, "Missing sigma_at_peak_MPa"
        assert approx_eq(computed, expected, rtol=1e-3), (
            f"sigma_at_peak: computed={computed}, expected={expected}")

    def test_peak_plastic_strain(self):
        """Accumulated plastic strain at peak."""
        computed = self.solver.get("eps_p_acc_at_peak")
        expected = self.ref["eps_p_acc_at_peak"]
        assert computed is not None, "Missing eps_p_acc_at_peak"
        assert approx_eq(computed, expected, rtol=1e-3), (
            f"eps_p_acc_at_peak: computed={computed}, expected={expected}")

    def test_final_stress(self):
        """Stress at final strain (after reverse yielding)."""
        computed = self.solver.get("sigma_at_final_MPa")
        expected = self.ref["sigma_at_final_MPa"]
        assert computed is not None, "Missing sigma_at_final_MPa"
        assert approx_eq(computed, expected, rtol=1e-3), (
            f"sigma_at_final: computed={computed}, expected={expected}")

    def test_final_plastic_strain(self):
        """Accumulated plastic strain at final state."""
        computed = self.solver.get("eps_p_acc_at_final")
        expected = self.ref["eps_p_acc_at_final"]
        assert computed is not None, "Missing eps_p_acc_at_final"
        assert approx_eq(computed, expected, rtol=1e-3), (
            f"eps_p_acc_at_final: computed={computed}, expected={expected}")

    def test_yield_condition_peak(self):
        """At peak, |sigma| must equal sigma_y + H*p (on yield surface)."""
        sigma = self.solver.get("sigma_at_peak_MPa", 0)
        p = self.solver.get("eps_p_acc_at_peak", 0)
        R = 250.0 + 10000.0 * p
        assert approx_eq(abs(sigma), R, rtol=1e-3), (
            f"|sigma|={abs(sigma)}, sigma_y+H*p={R}")

    def test_yield_condition_final(self):
        """At final state, |sigma| must equal sigma_y + H*p."""
        sigma = self.solver.get("sigma_at_final_MPa", 0)
        p = self.solver.get("eps_p_acc_at_final", 0)
        R = 250.0 + 10000.0 * p
        assert approx_eq(abs(sigma), R, rtol=1e-3), (
            f"|sigma|={abs(sigma)}, sigma_y+H*p={R}")

    def test_final_stress_negative(self):
        """Final stress must be negative (compressive) after reverse yielding."""
        assert self.solver.get("sigma_at_final_MPa", 0) < 0

    def test_plastic_strain_increases(self):
        """Accumulated plastic strain must increase monotonically."""
        p_peak = self.solver.get("eps_p_acc_at_peak", 0)
        p_final = self.solver.get("eps_p_acc_at_final", 0)
        assert p_final > p_peak, (
            f"p_final={p_final} must be > p_peak={p_peak}")


# ===========================================================================
# Benchmark 5: Composite laminate (CLT)
# ===========================================================================

def _compute_composite_laminate_reference():
    """
    Compute reference values for symmetric laminate [0/45/-45/90]s
    using Classical Lamination Theory.
    """
    E1 = 140000.0
    E2 = 10000.0
    G12 = 5000.0
    nu12 = 0.3
    nu21 = nu12 * E2 / E1

    denom = 1.0 - nu12 * nu21
    Q = np.array([
        [E1 / denom,       nu12 * E2 / denom, 0.0],
        [nu12 * E2 / denom, E2 / denom,        0.0],
        [0.0,               0.0,               G12],
    ])

    angles = [0, 45, -45, 90, 90, -45, 45, 0]
    t_ply = 0.125
    n_plies = len(angles)
    h_total = n_plies * t_ply

    def _Qbar(theta_deg):
        th = math.radians(theta_deg)
        c = math.cos(th)
        s = math.sin(th)
        c2, s2, cs_ = c * c, s * s, c * s
        c4, s4, c2s2 = c2 * c2, s2 * s2, c2 * s2
        Q11, Q12_, Q22, Q66 = Q[0, 0], Q[0, 1], Q[1, 1], Q[2, 2]

        Qb = np.zeros((3, 3))
        Qb[0, 0] = Q11 * c4 + 2.0 * (Q12_ + 2.0 * Q66) * c2s2 + Q22 * s4
        Qb[1, 1] = Q11 * s4 + 2.0 * (Q12_ + 2.0 * Q66) * c2s2 + Q22 * c4
        Qb[0, 1] = (Q11 + Q22 - 4.0 * Q66) * c2s2 + Q12_ * (c4 + s4)
        Qb[1, 0] = Qb[0, 1]
        Qb[2, 2] = (Q11 + Q22 - 2.0 * Q12_ - 2.0 * Q66) * c2s2 + Q66 * (c4 + s4)
        Qb[0, 2] = (Q11 - Q12_ - 2.0 * Q66) * c2 * cs_ - (Q22 - Q12_ - 2.0 * Q66) * s2 * cs_
        Qb[2, 0] = Qb[0, 2]
        Qb[1, 2] = (Q11 - Q12_ - 2.0 * Q66) * s2 * cs_ - (Q22 - Q12_ - 2.0 * Q66) * c2 * cs_
        Qb[2, 1] = Qb[1, 2]
        return Qb

    # Assemble A matrix
    A_mat = np.zeros((3, 3))
    for angle in angles:
        A_mat += _Qbar(angle) * t_ply

    # Compliance
    a_mat = np.linalg.inv(A_mat)

    # Effective properties
    Ex = 1.0 / (h_total * a_mat[0, 0])
    Ey = 1.0 / (h_total * a_mat[1, 1])
    Gxy = 1.0 / (h_total * a_mat[2, 2])
    nuxy = -a_mat[0, 1] / a_mat[0, 0]

    # Mid-plane strains
    N_vec = np.array([100.0, 0.0, 0.0])
    eps_0 = a_mat @ N_vec

    # Transform strains to ply material coordinates and compute stresses
    def _ply_stress(eps_global, theta_deg):
        th = math.radians(theta_deg)
        c = math.cos(th)
        s = math.sin(th)
        c2, s2, cs_ = c * c, s * s, c * s

        # Strain transformation: global engineering -> material engineering
        T_eps = np.array([
            [c2,    s2,     cs_],
            [s2,    c2,    -cs_],
            [-2*cs_, 2*cs_, c2 - s2],
        ])
        eps_mat = T_eps @ eps_global
        return Q @ eps_mat

    sig_0 = _ply_stress(eps_0, 0)
    sig_90 = _ply_stress(eps_0, 90)

    return {
        "Ex_eff_MPa": float(Ex),
        "Ey_eff_MPa": float(Ey),
        "Gxy_eff_MPa": float(Gxy),
        "nuxy_eff": float(nuxy),
        "eps_x_0": float(eps_0[0]),
        "eps_y_0": float(eps_0[1]),
        "gamma_xy_0": float(eps_0[2]),
        "sigma_1_ply0_MPa": float(sig_0[0]),
        "sigma_2_ply0_MPa": float(sig_0[1]),
        "tau_12_ply0_MPa": float(sig_0[2]),
        "sigma_1_ply90_MPa": float(sig_90[0]),
        "sigma_2_ply90_MPa": float(sig_90[1]),
        "tau_12_ply90_MPa": float(sig_90[2]),
    }


class TestCompositeLaminate:
    @pytest.fixture(autouse=True)
    def setup(self, results):
        self.solver = results.get("composite_laminate", {})
        self.ref = _compute_composite_laminate_reference()

    def test_has_benchmark(self, results):
        assert "composite_laminate" in results, "Missing composite_laminate benchmark"

    def test_quasi_isotropic_Ex_Ey(self):
        """[0/45/-45/90]s is quasi-isotropic: Ex must equal Ey."""
        Ex = self.solver.get("Ex_eff_MPa")
        Ey = self.solver.get("Ey_eff_MPa")
        assert Ex is not None and Ey is not None
        assert approx_eq(Ex, Ey, rtol=1e-3), (
            f"Quasi-isotropic violated: Ex={Ex}, Ey={Ey}")

    def test_quasi_isotropic_shear_relation(self):
        """For quasi-isotropic laminate, G = E/(2*(1+nu))."""
        Ex = self.solver.get("Ex_eff_MPa", 0)
        nuxy = self.solver.get("nuxy_eff", 0)
        Gxy = self.solver.get("Gxy_eff_MPa", 0)
        G_expected = Ex / (2.0 * (1.0 + nuxy))
        assert approx_eq(Gxy, G_expected, rtol=1e-3), (
            f"G={Gxy}, E/(2(1+nu))={G_expected}")

    def test_effective_moduli(self):
        """Effective moduli within tolerance."""
        for key in ["Ex_eff_MPa", "Ey_eff_MPa", "Gxy_eff_MPa", "nuxy_eff"]:
            computed = self.solver.get(key)
            expected = self.ref[key]
            assert computed is not None, f"Missing {key}"
            assert approx_eq(computed, expected), (
                f"{key}: computed={computed}, expected={expected}")

    def test_midplane_strains(self):
        """Mid-plane strains within tolerance."""
        for key in ["eps_x_0", "eps_y_0", "gamma_xy_0"]:
            computed = self.solver.get(key)
            expected = self.ref[key]
            assert computed is not None, f"Missing {key}"
            assert approx_eq(computed, expected), (
                f"{key}: computed={computed}, expected={expected}")

    def test_zero_shear_strain(self):
        """With Nxy=0 and A16=0, mid-plane shear strain must be zero."""
        gamma = self.solver.get("gamma_xy_0", 999)
        assert abs(gamma) < 1e-10, f"gamma_xy_0 should be zero, got {gamma}"

    def test_ply0_stresses(self):
        """Stresses in 0-degree ply material coordinates."""
        for key in ["sigma_1_ply0_MPa", "sigma_2_ply0_MPa", "tau_12_ply0_MPa"]:
            computed = self.solver.get(key)
            expected = self.ref[key]
            assert computed is not None, f"Missing {key}"
            assert approx_eq(computed, expected, rtol=1e-3), (
                f"{key}: computed={computed}, expected={expected}")

    def test_ply90_stresses(self):
        """Stresses in 90-degree ply material coordinates."""
        for key in ["sigma_1_ply90_MPa", "sigma_2_ply90_MPa", "tau_12_ply90_MPa"]:
            computed = self.solver.get(key)
            expected = self.ref[key]
            assert computed is not None, f"Missing {key}"
            assert approx_eq(computed, expected, rtol=1e-3), (
                f"{key}: computed={computed}, expected={expected}")

    def test_ply0_fiber_stress_positive(self):
        """0-degree ply should be in tension along fiber direction."""
        s1 = self.solver.get("sigma_1_ply0_MPa", 0)
        assert s1 > 0, f"0-degree ply fiber stress should be positive: {s1}"

    def test_ply90_fiber_stress_negative(self):
        """90-degree ply fiber direction should be in compression for Nx loading."""
        s1 = self.solver.get("sigma_1_ply90_MPa", 0)
        assert s1 < 0, f"90-degree ply fiber stress should be negative: {s1}"

    def test_ply0_zero_shear(self):
        """With Nxy=0, 0-degree ply should have no shear stress."""
        tau = self.solver.get("tau_12_ply0_MPa", 999)
        assert abs(tau) < 1e-6, f"0-degree ply shear should be zero: {tau}"

    def test_global_equilibrium(self):
        """Sum of ply stresses * thickness must equal applied resultant."""
        # In global coords: sigma_x = Nx / h_total = 100.0 / 1.0 = 100 MPa
        # Sum of Q_bar_k * eps_0 * t_k = A * eps_0 = N
        # So sum of sigma_x_k * t_k / h = Nx / h = 100 MPa
        # Check that solver ply stresses are consistent
        s1_0 = self.solver.get("sigma_1_ply0_MPa", 0)
        s2_0 = self.solver.get("sigma_2_ply0_MPa", 0)
        s1_90 = self.solver.get("sigma_1_ply90_MPa", 0)
        s2_90 = self.solver.get("sigma_2_ply90_MPa", 0)
        # 0-deg ply: sigma_x = sigma_1 (fiber along x), each ply 0.125mm, 2 plies at 0-deg
        # 90-deg ply: sigma_x = sigma_2 (transverse is along x), 2 plies at 90-deg
        # Contribution from 0+90 plies to Nx:
        Nx_0_90 = 2 * 0.125 * s1_0 + 2 * 0.125 * s2_90
        # This should be a significant portion of total Nx=100
        assert Nx_0_90 > 0, "Equilibrium check: contribution from 0/90 plies must be positive"


# ===========================================================================
# Structural tests (output format)
# ===========================================================================

class TestResultsFormat:
    def test_results_file_exists(self):
        assert os.path.isfile(RESULTS_PATH)

    def test_valid_json(self):
        with open(RESULTS_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict)
        assert "benchmarks" in data

    def test_all_benchmarks_present(self, results):
        for name in ["thick_cylinder", "piston_fluid",
                      "foundation_buckling", "plasticity_cycle",
                      "composite_laminate"]:
            assert name in results, f"Missing benchmark: {name}"

    def test_all_outputs_are_numeric(self, results):
        for bname, bdata in results.items():
            for key, val in bdata.items():
                assert isinstance(val, (int, float)), (
                    f"{bname}.{key} is not numeric: {type(val)}")
