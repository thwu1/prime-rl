
import pytest
import math
import sys
import numpy as np

sys.path.insert(0, "/app")
import waterway


# ======================== Darcy Friction Tests ========================

class TestDarcyFriction:
    """Tests for the Darcy friction factor computation."""

    def test_laminar_regime(self):
        """Laminar flow: fD = 64/Re for Re < 2100."""
        assert waterway.darcy_friction(500.0, 1.0, 0.0) == pytest.approx(0.128, rel=1e-10)
        assert waterway.darcy_friction(1000.0, 1.0, 0.0) == pytest.approx(0.064, rel=1e-10)
        assert waterway.darcy_friction(2000.0, 2.0, 0.001) == pytest.approx(0.032, rel=1e-10)

    def test_turbulent_regime(self):
        """Turbulent flow (Re > 2300) using Swamee-Jain approximation."""
        # Re=100000, D=3.3, eps=0.001
        # Swamee-Jain: fD = 1/(2*log10(eps/(3.7D) + 5.74/Re^0.9))^2
        # Precomputed: fD ≈ 0.01951
        fD = waterway.darcy_friction(100000.0, 3.3, 0.001)
        assert fD == pytest.approx(0.01951, rel=2e-2)
        assert fD > 0

        # Re=50000, D=1.0, eps=0.001 → fD ≈ 0.02418
        fD2 = waterway.darcy_friction(50000.0, 1.0, 0.001)
        assert fD2 == pytest.approx(0.02418, rel=2e-2)

        # Higher roughness should give higher friction
        fD_rough = waterway.darcy_friction(100000.0, 3.3, 0.01)
        assert fD_rough > fD

    def test_transition_continuity(self):
        """C0 continuity: fD must be continuous at Re=2100 and Re=2300."""
        D, eps = 3.3, 0.001
        delta = 0.01

        # At Re=2100 boundary
        f_below = waterway.darcy_friction(2100.0 - delta, D, eps)
        f_at = waterway.darcy_friction(2100.0, D, eps)
        f_above = waterway.darcy_friction(2100.0 + delta, D, eps)
        assert abs(f_at - f_below) < 1e-4, "Discontinuity at Re=2100 lower"
        assert abs(f_at - f_above) < 1e-4, "Discontinuity at Re=2100 upper"

        # Must match laminar value at Re=2100
        assert f_at == pytest.approx(64.0 / 2100.0, rel=1e-6)

        # At Re=2300 boundary
        f_below_t = waterway.darcy_friction(2300.0 - delta, D, eps)
        f_at_t = waterway.darcy_friction(2300.0, D, eps)
        f_above_t = waterway.darcy_friction(2300.0 + delta, D, eps)
        assert abs(f_at_t - f_below_t) < 1e-4, "Discontinuity at Re=2300 lower"
        assert abs(f_at_t - f_above_t) < 1e-4, "Discontinuity at Re=2300 upper"

    def test_transition_c1_continuity(self):
        """C1 continuity: first derivative must be continuous at regime boundaries."""
        D, eps = 3.3, 0.001
        h = 0.1

        # At Re=2100: derivative should match d(64/Re)/dRe = -64/Re^2
        expected_slope_2100 = -64.0 / 2100.0**2
        numerical_slope = (waterway.darcy_friction(2100.0 + h, D, eps) -
                           waterway.darcy_friction(2100.0 - h, D, eps)) / (2 * h)
        assert numerical_slope == pytest.approx(expected_slope_2100, rel=5e-2), \
            f"C1 failure at Re=2100: numerical={numerical_slope}, expected={expected_slope_2100}"

        # At Re=2300: numerical derivative from both sides should match
        slope_below = (waterway.darcy_friction(2300.0, D, eps) -
                       waterway.darcy_friction(2300.0 - h, D, eps)) / h
        slope_above = (waterway.darcy_friction(2300.0 + h, D, eps) -
                       waterway.darcy_friction(2300.0, D, eps)) / h
        assert slope_below == pytest.approx(slope_above, rel=0.1), \
            f"C1 failure at Re=2300: below={slope_below}, above={slope_above}"


# ======================== Friction Force Test ========================

class TestFrictionForce:
    """Tests for the Darcy-Weisbach friction force."""

    def test_friction_force_basic(self):
        """Check friction force against manual computation."""
        v, D, L, rho, mu, eps = 2.0, 3.3, 100.0, 1000.0, 1e-3, 0.001
        F = waterway.friction_force(v, D, L, rho, mu, eps)

        # Re = rho*|v|*D/mu = 1000*2*3.3/1e-3 = 6,600,000 (turbulent)
        Re = rho * abs(v) * D / mu
        assert Re > 2300  # confirm turbulent

        # F = pi/8 * fD * rho * L * D * v * |v|
        fD = waterway.darcy_friction(Re, D, eps)
        expected = math.pi / 8 * fD * rho * L * D * v * abs(v)
        assert F == pytest.approx(expected, rel=1e-6)

        # Force should be positive when v > 0
        assert F > 0

    def test_friction_force_sign(self):
        """Friction force reverses sign with velocity."""
        v, D, L, rho, mu, eps = -1.5, 2.0, 50.0, 998.0, 1.1e-3, 0.0005
        F_neg = waterway.friction_force(v, D, L, rho, mu, eps)
        F_pos = waterway.friction_force(-v, D, L, rho, mu, eps)
        # F = ... * v * |v| → changes sign with v, same magnitude
        assert F_neg == pytest.approx(-F_pos, rel=1e-10)


# ======================== Gate Discharge Tests ========================

class TestGateDischarge:
    """Tests for Bollrich gate discharge equations."""

    def test_sluice_free_flow(self):
        """Sluice gate in free-flow regime (h2 < h2_limit)."""
        Vdot = waterway.gate_discharge(
            gate_type='sluice', a=1.0, h_0=5.0, h_2=0.5, b=3.0)

        # Precomputed: psi ≈ 0.6146, mu_A ≈ 0.5800, chi=1 (free)
        # Vdot = mu_A * A * sqrt(2*g*h0) ≈ 0.5800 * 3.0 * sqrt(98.1) ≈ 17.24
        assert Vdot == pytest.approx(17.24, rel=2e-2)
        assert Vdot > 0

    def test_sluice_backed_up_flow(self):
        """Sluice gate in backed-up (submerged) flow regime."""
        Vdot = waterway.gate_discharge(
            gate_type='sluice', a=1.0, h_0=5.0, h_2=4.0, b=3.0)

        # h_2=4.0 > h_2_limit ≈ 3.015 → backed-up flow with chi < 1
        # Precomputed: chi ≈ 0.556, Vdot ≈ 9.58
        assert Vdot == pytest.approx(9.58, rel=3e-2)

        # Backed-up flow should give less discharge than free flow
        Vdot_free = waterway.gate_discharge(
            gate_type='sluice', a=1.0, h_0=5.0, h_2=0.5, b=3.0)
        assert Vdot < Vdot_free

    def test_radial_gate_free_flow(self):
        """Radial (tainter) gate in free-flow regime."""
        Vdot = waterway.gate_discharge(
            gate_type='radial', a=0.3, h_0=3.0, h_2=0.3, b=4.0,
            r=2.0, h_h=1.5)

        # Precomputed: alpha ≈ 53.1°, psi ≈ 0.721, mu_A ≈ 0.697
        # Vdot ≈ 6.41
        assert Vdot == pytest.approx(6.41, rel=3e-2)
        assert Vdot > 0


# ======================== Francis Turbine Test ========================

class TestFrancisPower:
    """Tests for the Francis turbine Euler power equation."""

    def test_francis_shaft_power(self):
        """Check Euler equation at a known operating point."""
        Wdot = waterway.francis_power(
            mdot=20000.0, omega=50.0, R_1=1.0, R_2=0.5,
            w_1=0.3, alpha1_deg=45.0, beta2_deg=150.0,
            D_i=2.0, rho=1000.0)

        # Precomputed:
        # A1 = 2*pi*1.0*0.3 = 1.8850; A2 = pi*0.25 = 0.7854
        # Vdot = 20; cot(45)=1; cot(150)=-sqrt(3)
        # W_t1 = 20000*50*1.0*(20/1.8850)*1.0 ≈ 10.61 MW
        # W_t2 = 20000*50*0.5*(25 + 25.465*(-1.732)) ≈ -9.55 MW
        # Wdot = 10.61 - (-9.55) ≈ 20.16 MW
        assert Wdot == pytest.approx(20.16e6, rel=2e-2)
        assert Wdot > 0  # shaft power should be positive

    def test_francis_zero_flow(self):
        """Zero mass flow → zero power."""
        Wdot = waterway.francis_power(
            mdot=0.0, omega=50.0, R_1=1.0, R_2=0.5,
            w_1=0.3, alpha1_deg=45.0, beta2_deg=150.0,
            D_i=2.0, rho=1000.0)
        assert Wdot == pytest.approx(0.0, abs=1e-6)


# ======================== Elastic Penstock Tests ========================

class TestElasticPenstock:
    """Tests for the KP07 elastic penstock simulation."""

    @pytest.fixture
    def horizontal_penstock(self):
        """Create a horizontal frictionless penstock for clean wave tests."""
        return waterway.ElasticPenstock(
            L=500.0, H=0.0, D_i=2.0, D_o=2.0, N=10,
            rho=1000.0, mu=1e-3, beta=4.5e-10,
            beta_total=1e-9, p_eps=0.0, p_a=0.0, g=9.81, theta=1.3)

    def test_steady_state_preservation(self, horizontal_penstock):
        """Uniform flow with matching BCs should stay near steady state."""
        pen = horizontal_penstock
        Vdot_0 = 5.0
        mdot_0 = pen.rho * Vdot_0
        p0 = 5e5

        result = pen.simulate(
            t_end=0.1, dt=0.005,
            p_inlet_func=lambda t: p0,
            mdot_outlet_func=lambda t: mdot_0,
            Vdot_0=Vdot_0)

        # Pressures should remain near initial (H=0 → uniform initial pressure)
        initial_p = result['pressures'][0, :]
        final_p = result['pressures'][-1, :]
        max_drift = np.max(np.abs(final_p - initial_p))
        # Allow up to 5% of initial pressure as drift
        assert max_drift < 0.05 * p0, \
            f"Pressure drifted by {max_drift:.0f} Pa in steady state"

    def test_water_hammer_joukowsky(self, horizontal_penstock):
        """Valve closure should produce Joukowsky pressure rise."""
        pen = horizontal_penstock
        Vdot_0 = 5.0
        mdot_0 = pen.rho * Vdot_0
        p0 = 5e5
        A = math.pi * pen.D_i**2 / 4
        v0 = Vdot_0 / A

        # Analytical wave speed and Joukowsky pressure rise
        c = math.sqrt(1.0 / (pen.rho * pen.beta_total))
        dp_joukowsky = pen.rho * c * v0

        # Simulate valve closure at t ≈ 0
        def mdot_outlet(t):
            return mdot_0 if t < 0.001 else 0.0

        result = pen.simulate(
            t_end=1.0, dt=0.005,
            p_inlet_func=lambda t: p0,
            mdot_outlet_func=mdot_outlet,
            Vdot_0=Vdot_0)

        # Check peak pressure at outlet (last cell)
        outlet_pressures = result['pressures'][:, -1]
        peak_pressure = np.max(outlet_pressures)

        # Peak should be approximately p0 + dp_joukowsky
        expected_peak = p0 + dp_joukowsky
        assert peak_pressure > 0.7 * expected_peak, \
            f"Peak pressure {peak_pressure:.0f} too low (expected ~{expected_peak:.0f})"
        assert peak_pressure < 1.5 * expected_peak, \
            f"Peak pressure {peak_pressure:.0f} too high (expected ~{expected_peak:.0f})"

    def test_water_hammer_wave_propagation(self, horizontal_penstock):
        """Pressure wave should propagate at approximately the wave speed c."""
        pen = horizontal_penstock
        Vdot_0 = 5.0
        mdot_0 = pen.rho * Vdot_0
        p0 = 5e5
        c = math.sqrt(1.0 / (pen.rho * pen.beta_total))
        travel_time = pen.L / c  # time for wave to cross pipe

        def mdot_outlet(t):
            return mdot_0 if t < 0.001 else 0.0

        result = pen.simulate(
            t_end=1.5 * travel_time, dt=0.005,
            p_inlet_func=lambda t: p0,
            mdot_outlet_func=mdot_outlet,
            Vdot_0=Vdot_0)

        times = result['times']
        inlet_pressures = result['pressures'][:, 0]

        # Before wave arrives at inlet, pressure should be near initial
        early_mask = times < 0.5 * travel_time
        if np.any(early_mask):
            early_max_change = np.max(np.abs(inlet_pressures[early_mask] - p0))
            assert early_max_change < 0.15 * p0, \
                "Inlet pressure changed before wave should arrive"

        # After wave arrives at inlet, pressure should have changed
        late_mask = times > 1.2 * travel_time
        if np.any(late_mask):
            late_change = np.max(np.abs(inlet_pressures[late_mask] - p0))
            # With constant pressure BC at inlet, the wave reflects back
            # but should still cause some perturbation in flows
            # Check outlet: should show significant pressure change
            outlet_late = result['pressures'][late_mask, -1]
            outlet_change = np.max(np.abs(outlet_late - p0))
            assert outlet_change > 0.1 * p0, \
                "No significant pressure change at outlet after wave propagation"

    def test_mass_conservation(self, horizontal_penstock):
        """Total mass in the pipe should be approximately conserved."""
        pen = horizontal_penstock
        Vdot_0 = 5.0
        mdot_0 = pen.rho * Vdot_0
        p0 = 5e5

        def mdot_outlet(t):
            return mdot_0 if t < 0.001 else 0.0

        result = pen.simulate(
            t_end=0.5, dt=0.005,
            p_inlet_func=lambda t: p0,
            mdot_outlet_func=mdot_outlet,
            Vdot_0=Vdot_0)

        # Compute total mass at each time step
        # rho(p) = rho0 * (1 + beta*(p-pa))
        # A(p) = A_atm * (Fap/rho) where Fap = rho0*A_atm*(1+bt*(p-pa))
        # mass per cell = rho * A * dx = Fap * dx
        dx = pen.L / pen.N
        A_atm = math.pi * pen.D_i**2 / 4

        masses = []
        for t_idx in range(len(result['times'])):
            pp = result['pressures'][t_idx, :]
            Fap = pen.rho * A_atm * (1 + pen.beta_total * (pp - pen.p_a))
            total_mass = np.sum(Fap) * dx
            masses.append(total_mass)

        masses = np.array(masses)
        initial_mass = masses[0]

        # Mass change should be small relative to initial mass
        # (some change expected due to inlet/outlet fluxes)
        max_deviation = np.max(np.abs(masses - initial_mass))
        assert max_deviation < 0.1 * initial_mass, \
            f"Mass changed by {max_deviation/initial_mass*100:.1f}% — too large"
