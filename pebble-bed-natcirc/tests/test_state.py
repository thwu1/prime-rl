"""
Tests for pebble-bed HTGR natural circulation simulation.

Verifies the agent's corrected simulation output against an independent
reference solver implementation.

"""
import csv
import math
import os
import tomllib

import numpy as np
import pytest

G_ACCEL = 9.80665
RESULTS_PATH = "/app/results.csv"
CONFIG_PATH = "/app/reactor.toml"

EXPECTED_COLUMNS = [
    "time_hours",
    "decay_heat_MW",
    "mass_flow_rate_kg_s",
    "outlet_temp_K",
    "peak_surface_temp_K",
    "peak_centerline_temp_K",
    "core_dp_Pa",
]


# ---------------------------------------------------------------------------
# Reference solver (independent implementation for verification)
# ---------------------------------------------------------------------------

def _ref_solve(q_total, t_inlet, pressure, conf, num_nodes):
    """Independent reference solver for natural circulation."""
    core_h = conf["core"]["height_m"]
    core_r = conf["core"]["radius_m"]
    peb_d = conf["core"]["pebble_diameter_m"]
    void_frac = conf["core"]["porosity"]
    xs_area = np.pi * core_r**2

    ch_h = conf["chimney"]["height_m"]
    ch_a = conf["chimney"]["flow_area_m2"]
    ch_dh = conf["chimney"]["hydraulic_diameter_m"]
    ch_f = conf["chimney"]["friction_factor"]

    he = conf["helium"]
    spec_heat = he["cp"]
    r_gas = he["R_specific"]
    visc_a, visc_b = he["mu_coeff"], he["mu_exp"]
    cond_a, cond_b = he["k_coeff"], he["k_exp"]

    gr_ka = conf["graphite"]["k_a"]
    gr_kb = conf["graphite"]["k_b"]

    step = core_h / num_nodes
    zz = np.linspace(step / 2, core_h - step / 2, num_nodes)

    qp = q_total * np.pi / (2.0 * xs_area * core_h)
    heat_dist = qp * np.sin(np.pi * zz / core_h)

    den_inlet = pressure / (r_gas * t_inlet)

    def _balance(flow):
        tf = t_inlet + (q_total / (2.0 * flow * spec_heat)) * (
            1.0 - np.cos(np.pi * zz / core_h)
        )
        t_exit = t_inlet + q_total / (flow * spec_heat)
        if t_exit > 5000.0:
            return 1e10

        den_f = pressure / (r_gas * tf)
        den_exit = pressure / (r_gas * t_exit)

        drv = G_ACCEL * (np.sum((den_inlet - den_f) * step) +
                         ch_h * (den_inlet - den_exit))

        us = flow / (den_f * xs_area)
        visc = visc_a * tf**visc_b
        fv = 150.0 * visc * us * (1 - void_frac)**2 / (peb_d**2 * void_frac**3)
        fi = 1.75 * den_f * us**2 * (1 - void_frac) / (peb_d * void_frac**3)
        loss_core = np.sum((fv + fi) * step)

        uc = flow / (den_exit * ch_a)
        loss_ch = ch_f * (ch_h / ch_dh) * 0.5 * den_exit * uc**2

        return drv - loss_core - loss_ch

    lo, hi = 0.001, 200.0
    for _ in range(300):
        mid = (lo + hi) / 2.0
        if _balance(mid) > 0:
            lo = mid
        else:
            hi = mid
        if (hi - lo) / mid < 1e-12:
            break
    flow_sol = (lo + hi) / 2.0

    tf = t_inlet + (q_total / (2.0 * flow_sol * spec_heat)) * (
        1.0 - np.cos(np.pi * zz / core_h)
    )
    t_exit = t_inlet + q_total / (flow_sol * spec_heat)

    den_f = pressure / (r_gas * tf)
    us = flow_sol / (den_f * xs_area)
    visc = visc_a * tf**visc_b
    cond_f = cond_a * tf**cond_b
    pr = visc * spec_heat / cond_f
    re = den_f * us * peb_d / visc
    nu = 2.0 + 1.1 * re**0.6 * pr**(1.0 / 3.0)
    hc = nu * cond_f / peb_d
    hv = 6.0 * (1.0 - void_frac) * hc / peb_d

    t_peb_surf = tf + heat_dist / hv
    max_surf = float(np.max(t_peb_surf))

    rad = peb_d / 2.0
    qv_peb = heat_dist / (1.0 - void_frac)
    c_int = qv_peb * rad**2 / 6.0
    t_peb_ctr = ((gr_ka + gr_kb * t_peb_surf) *
                 np.exp(gr_kb * c_int) - gr_ka) / gr_kb
    max_ctr = float(np.max(t_peb_ctr))

    fv = 150.0 * visc * us * (1 - void_frac)**2 / (peb_d**2 * void_frac**3)
    fi = 1.75 * den_f * us**2 * (1 - void_frac) / (peb_d * void_frac**3)
    core_dp = float(np.sum((fv + fi) * step))

    return {
        "mdot": flow_sol,
        "T_out": t_exit,
        "peak_surf": max_surf,
        "peak_ctr": max_ctr,
        "dp_core": core_dp,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def config():
    with open(CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


@pytest.fixture(scope="module")
def agent_results():
    """Parse agent's results.csv."""
    assert os.path.isfile(RESULTS_PATH), f"Output file {RESULTS_PATH} not found"
    rows = []
    with open(RESULTS_PATH, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({k: float(v) for k, v in row.items()})
    return rows


@pytest.fixture(scope="module")
def reference_results(config):
    """Compute reference solutions for all time points."""
    P = config["conditions"]["pressure_Pa"]
    T_in = config["conditions"]["inlet_temperature_K"]
    Q0 = config["conditions"]["thermal_power_W"]
    n_nodes = config["simulation"]["n_axial_nodes"]
    times = config["simulation"]["time_points_hours"]
    dc = config["decay_heat"]["coefficient"]
    de = config["decay_heat"]["exponent"]

    refs = []
    for t_hr in times:
        t_s = t_hr * 3600.0
        Q = Q0 * dc * t_s**de
        sol = _ref_solve(Q, T_in, P, config, n_nodes)
        sol["time_hours"] = t_hr
        sol["decay_MW"] = Q / 1e6
        refs.append(sol)
    return refs


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestOutputFormat:
    """Verify the output file format is correct."""

    def test_file_exists(self):
        assert os.path.isfile(RESULTS_PATH), "results.csv not found at /app/results.csv"

    def test_has_correct_columns(self, agent_results):
        row = agent_results[0]
        for col in EXPECTED_COLUMNS:
            assert col in row, f"Missing column: {col}"

    def test_has_correct_number_of_rows(self, agent_results, config):
        n_expected = len(config["simulation"]["time_points_hours"])
        assert len(agent_results) == n_expected, (
            f"Expected {n_expected} rows, got {len(agent_results)}"
        )

    def test_time_points_match(self, agent_results, config):
        expected_times = config["simulation"]["time_points_hours"]
        agent_times = [r["time_hours"] for r in agent_results]
        for et, at in zip(expected_times, agent_times):
            assert abs(et - at) < 0.01, f"Time mismatch: expected {et}, got {at}"


class TestPhysicalConsistency:
    """Verify physical consistency of results."""

    def test_positive_flow_rates(self, agent_results):
        for row in agent_results:
            assert row["mass_flow_rate_kg_s"] > 0

    def test_outlet_above_inlet(self, agent_results, config):
        T_in = config["conditions"]["inlet_temperature_K"]
        for row in agent_results:
            assert row["outlet_temp_K"] > T_in

    def test_surface_above_outlet(self, agent_results):
        for row in agent_results:
            assert row["peak_surface_temp_K"] >= row["outlet_temp_K"] * 0.95

    def test_centerline_above_surface(self, agent_results):
        for row in agent_results:
            assert row["peak_centerline_temp_K"] >= row["peak_surface_temp_K"] - 0.1

    def test_energy_conservation(self, agent_results, config):
        cp = config["helium"]["cp"]
        T_in = config["conditions"]["inlet_temperature_K"]
        for row in agent_results:
            Q_balance = row["mass_flow_rate_kg_s"] * cp * (row["outlet_temp_K"] - T_in)
            Q_decay = row["decay_heat_MW"] * 1e6
            rel_err = abs(Q_balance - Q_decay) / Q_decay
            assert rel_err < 0.005, (
                f"Energy conservation error {rel_err:.4f} at t={row['time_hours']}h"
            )

    def test_decay_heat_decreases(self, agent_results):
        dh = [r["decay_heat_MW"] for r in agent_results]
        for i in range(len(dh) - 1):
            assert dh[i] > dh[i + 1]

    def test_flow_rate_decreases(self, agent_results):
        flows = [r["mass_flow_rate_kg_s"] for r in agent_results]
        for i in range(len(flows) - 1):
            assert flows[i] > flows[i + 1]

    def test_positive_pressure_drop(self, agent_results):
        for row in agent_results:
            assert row["core_dp_Pa"] > 0

    def test_pressure_drop_decreases(self, agent_results):
        dps = [r["core_dp_Pa"] for r in agent_results]
        for i in range(len(dps) - 1):
            assert dps[i] > dps[i + 1]


class TestDecayHeatValues:
    """Verify decay heat computation."""

    def test_decay_heat_formula(self, agent_results, config):
        Q0 = config["conditions"]["thermal_power_W"]
        dc = config["decay_heat"]["coefficient"]
        de = config["decay_heat"]["exponent"]
        for row in agent_results:
            t_s = row["time_hours"] * 3600.0
            Q_expected = Q0 * dc * t_s**de
            Q_agent = row["decay_heat_MW"] * 1e6
            rel_err = abs(Q_agent - Q_expected) / Q_expected
            assert rel_err < 0.001


class TestNumericalAccuracy:
    """Compare agent's results against the independent reference solver."""

    def test_mass_flow_rate(self, agent_results, reference_results):
        for ar, rr in zip(agent_results, reference_results):
            rel_err = abs(ar["mass_flow_rate_kg_s"] - rr["mdot"]) / rr["mdot"]
            assert rel_err < 0.03, (
                f"Mass flow rate error {rel_err:.4f} at t={ar['time_hours']}h. "
                f"Agent: {ar['mass_flow_rate_kg_s']:.4f}, Ref: {rr['mdot']:.4f}"
            )

    def test_outlet_temperature(self, agent_results, reference_results):
        for ar, rr in zip(agent_results, reference_results):
            abs_err = abs(ar["outlet_temp_K"] - rr["T_out"])
            assert abs_err < 5.0, (
                f"Outlet temp error {abs_err:.2f} K at t={ar['time_hours']}h. "
                f"Agent: {ar['outlet_temp_K']:.2f}, Ref: {rr['T_out']:.2f}"
            )

    def test_peak_surface_temperature(self, agent_results, reference_results):
        for ar, rr in zip(agent_results, reference_results):
            abs_err = abs(ar["peak_surface_temp_K"] - rr["peak_surf"])
            assert abs_err < 5.0, (
                f"Peak surface temp error {abs_err:.2f} K at t={ar['time_hours']}h. "
                f"Agent: {ar['peak_surface_temp_K']:.2f}, Ref: {rr['peak_surf']:.2f}"
            )

    def test_peak_centerline_temperature(self, agent_results, reference_results):
        for ar, rr in zip(agent_results, reference_results):
            abs_err = abs(ar["peak_centerline_temp_K"] - rr["peak_ctr"])
            assert abs_err < 5.0, (
                f"Peak centerline temp error {abs_err:.2f} K at t={ar['time_hours']}h. "
                f"Agent: {ar['peak_centerline_temp_K']:.2f}, Ref: {rr['peak_ctr']:.2f}"
            )

    def test_core_pressure_drop(self, agent_results, reference_results):
        for ar, rr in zip(agent_results, reference_results):
            rel_err = abs(ar["core_dp_Pa"] - rr["dp_core"]) / rr["dp_core"]
            assert rel_err < 0.03, (
                f"Core dP error {rel_err:.4f} at t={ar['time_hours']}h. "
                f"Agent: {ar['core_dp_Pa']:.2f}, Ref: {rr['dp_core']:.2f}"
            )


class TestMomentumBalance:
    """Verify that the agent's flow rate satisfies the momentum balance."""

    def test_buoyancy_equals_friction(self, agent_results, config):
        core = config["core"]
        chimney = config["chimney"]
        he = config["helium"]
        P = config["conditions"]["pressure_Pa"]
        T_in = config["conditions"]["inlet_temperature_K"]
        Q0 = config["conditions"]["thermal_power_W"]
        dc = config["decay_heat"]["coefficient"]
        de = config["decay_heat"]["exponent"]
        n = config["simulation"]["n_axial_nodes"]

        H = core["height_m"]
        R = core["radius_m"]
        dp_peb = core["pebble_diameter_m"]
        eps = core["porosity"]
        A = np.pi * R**2

        H_ch = chimney["height_m"]
        A_ch = chimney["flow_area_m2"]
        D_ch = chimney["hydraulic_diameter_m"]
        f_ch = chimney["friction_factor"]

        cp = he["cp"]
        R_sp = he["R_specific"]

        dz = H / n
        z = np.linspace(dz / 2, H - dz / 2, n)

        for row in agent_results:
            t_s = row["time_hours"] * 3600.0
            Q = Q0 * dc * t_s**de
            mdot = row["mass_flow_rate_kg_s"]

            T_f = T_in + (Q / (2.0 * mdot * cp)) * (1.0 - np.cos(np.pi * z / H))
            T_out = T_in + Q / (mdot * cp)

            rho_in = P / (R_sp * T_in)
            rho_f = P / (R_sp * T_f)
            rho_out = P / (R_sp * T_out)

            buoy = G_ACCEL * (np.sum((rho_in - rho_f) * dz) +
                              H_ch * (rho_in - rho_out))

            vs = mdot / (rho_f * A)
            mu = he["mu_coeff"] * T_f ** he["mu_exp"]
            ev = 150.0 * mu * vs * (1 - eps)**2 / (dp_peb**2 * eps**3)
            ei = 1.75 * rho_f * vs**2 * (1 - eps) / (dp_peb * eps**3)
            dp_c = np.sum((ev + ei) * dz)

            vc = mdot / (rho_out * A_ch)
            dp_chimney = f_ch * (H_ch / D_ch) * 0.5 * rho_out * vc**2

            friction = dp_c + dp_chimney
            rel_imbalance = abs(buoy - friction) / max(buoy, friction)

            assert rel_imbalance < 0.05, (
                f"Momentum imbalance {rel_imbalance:.4f} at t={row['time_hours']}h. "
                f"Buoyancy={buoy:.2f} Pa, Friction={friction:.2f} Pa"
            )
