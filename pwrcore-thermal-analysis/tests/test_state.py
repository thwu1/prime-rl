"""
PWR Hot Channel Safety Analysis Audit - Verification Tests

"""

import json
import math
import os
import shutil
import sqlite3
import subprocess

import pytest


RESULTS_PATH = "/app/results.json"
SPECS_PATH = "/app/reactor_specs.json"
DB_PATH = "/app/coolant.db"
ANALYSIS_SCRIPT = "/app/analysis.py"

# ---- Geometry constants from specs (for exact verification) ----
D_PIN = 9.50e-3       # m
P_PITCH = 12.60e-3    # m
MDOT = 0.350           # kg/s
L_ACTIVE = 3.658       # m
DELTA_EXT = 0.3048     # m

# Exact geometry
A_FLOW_EXACT = P_PITCH**2 - math.pi * D_PIN**2 / 4.0
PW_EXACT = math.pi * D_PIN
DH_EXACT = 4.0 * A_FLOW_EXACT / PW_EXACT
G_EXACT = MDOT / A_FLOW_EXACT


def load_results():
    """Load results.json produced by the agent's analysis."""
    assert os.path.exists(RESULTS_PATH), f"{RESULTS_PATH} not found"
    with open(RESULTS_PATH) as f:
        return json.load(f)


def load_db_props():
    """Load water properties from SQLite database for reference calculations."""
    temps, rhos, cps, mus, ks, hs = [], [], [], [], [], []
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT temperature_C, density_kg_m3, specific_heat_kJ_kgK, "
        "viscosity_Pa_s, thermal_conductivity_W_mK, enthalpy_kJ_kg "
        "FROM liquid_properties ORDER BY temperature_C"
    ).fetchall()
    conn.close()
    for row in rows:
        temps.append(row[0])
        rhos.append(row[1])
        cps.append(row[2])
        mus.append(row[3])
        ks.append(row[4])
        hs.append(row[5])
    return temps, rhos, cps, mus, ks, hs


def linterp(x_arr, y_arr, x):
    """Linear interpolation with clamping."""
    if x <= x_arr[0]:
        return y_arr[0]
    if x >= x_arr[-1]:
        return y_arr[-1]
    for i in range(len(x_arr) - 1):
        if x_arr[i] <= x <= x_arr[i + 1]:
            frac = (x - x_arr[i]) / (x_arr[i + 1] - x_arr[i])
            return y_arr[i] + frac * (y_arr[i + 1] - y_arr[i])
    return y_arr[-1]


def compute_reference_outlet_temp():
    """Independent 200-node integration to get reference outlet temperature."""
    temps, rhos, cps, mus, ks, hs = load_db_props()

    with open(SPECS_PATH) as f:
        specs = json.load(f)

    q_max = specs['operating_conditions']['peak_linear_heat_rate_kW_m'] * 1e3
    m_dot = specs['operating_conditions']['subchannel_mass_flow_rate_kg_s']
    T_in = specs['operating_conditions']['coolant_inlet_temperature_C']
    L = specs['geometry']['active_fuel_length_m']
    delta = specs['geometry']['extrapolation_distance_m']
    L_e = L + 2 * delta

    N = 200
    dz = L / (N - 1)
    h_kJ = linterp(temps, hs, T_in)

    for i in range(1, N):
        z = i * dz
        z_prev = (i - 1) * dz
        zm = z - L / 2
        zm_prev = z_prev - L / 2
        q1 = q_max * math.cos(math.pi * zm_prev / L_e)
        q2 = q_max * math.cos(math.pi * zm / L_e)
        q_avg = 0.5 * (q1 + q2)
        dh = q_avg * dz / (m_dot * 1000.0)
        h_kJ += dh

    T_out = linterp(hs, temps, h_kJ)
    return T_out


def compute_reference_peak_clad():
    """Independent computation of peak cladding temperature using correct physics."""
    temps, rhos, cps, mus, ks, hs = load_db_props()

    with open(SPECS_PATH) as f:
        specs = json.load(f)

    q_max = specs['operating_conditions']['peak_linear_heat_rate_kW_m'] * 1e3
    m_dot = specs['operating_conditions']['subchannel_mass_flow_rate_kg_s']
    T_in = specs['operating_conditions']['coolant_inlet_temperature_C']
    L = specs['geometry']['active_fuel_length_m']
    delta = specs['geometry']['extrapolation_distance_m']
    L_e = L + 2 * delta
    D_pin = specs['geometry']['fuel_pin_od_mm'] * 1e-3
    P_p = specs['geometry']['fuel_pin_pitch_mm'] * 1e-3

    A_f = P_p**2 - math.pi * D_pin**2 / 4.0
    D_hyd = 4.0 * A_f / (math.pi * D_pin)
    G_ref = m_dot / A_f

    N = 200
    dz = L / (N - 1)
    h_kJ = linterp(temps, hs, T_in)
    max_Tc = 0.0

    for i in range(N):
        z = i * dz
        zm = z - L / 2.0
        qp = q_max * math.cos(math.pi * zm / L_e)
        qf = qp / (math.pi * D_pin)

        if i > 0:
            zm_prev = (i - 1) * dz - L / 2.0
            qp_prev = q_max * math.cos(math.pi * zm_prev / L_e)
            q_avg = 0.5 * (qp_prev + qp)
            dh = q_avg * dz / (m_dot * 1000.0)
            h_kJ += dh

        T_b = linterp(hs, temps, h_kJ)
        rho = linterp(temps, rhos, T_b)
        cp_J = linterp(temps, cps, T_b) * 1000
        mu = linterp(temps, mus, T_b)
        kw = linterp(temps, ks, T_b)

        Re = G_ref * D_hyd / mu
        Pr = mu * cp_J / kw
        Nu = 0.023 * Re**0.8 * Pr**0.4
        hc = Nu * kw / D_hyd

        Tc = T_b + qf / hc
        if Tc > max_Tc:
            max_Tc = Tc

    return max_Tc


def compute_reference_min_dnbr():
    """Independent computation of minimum DNBR using correct W-3 correlation."""
    temps, rhos, cps, mus, ks, hs = load_db_props()

    with open(SPECS_PATH) as f:
        specs = json.load(f)

    q_max = specs['operating_conditions']['peak_linear_heat_rate_kW_m'] * 1e3
    m_dot = specs['operating_conditions']['subchannel_mass_flow_rate_kg_s']
    T_in = specs['operating_conditions']['coolant_inlet_temperature_C']
    L = specs['geometry']['active_fuel_length_m']
    delta = specs['geometry']['extrapolation_distance_m']
    L_e = L + 2 * delta
    D_pin = specs['geometry']['fuel_pin_od_mm'] * 1e-3
    P_p = specs['geometry']['fuel_pin_pitch_mm'] * 1e-3
    P_sys = specs['operating_conditions']['system_pressure_MPa']
    h_f_sat = specs['saturation_properties']['liquid_enthalpy_kJ_kg']
    h_fg_sat = specs['saturation_properties']['latent_heat_kJ_kg']

    A_f = P_p**2 - math.pi * D_pin**2 / 4.0
    D_hyd = 4.0 * A_f / (math.pi * D_pin)
    G_ref = m_dot / A_f
    h_in_kJ = linterp(temps, hs, T_in)

    N = 200
    dz = L / (N - 1)
    h_kJ = h_in_kJ
    min_dnbr = 999.0

    for i in range(N):
        z = i * dz
        zm = z - L / 2.0
        qp = q_max * math.cos(math.pi * zm / L_e)
        qf = qp / (math.pi * D_pin)

        if i > 0:
            zm_prev = (i - 1) * dz - L / 2.0
            qp_prev = q_max * math.cos(math.pi * zm_prev / L_e)
            q_avg = 0.5 * (qp_prev + qp)
            dh = q_avg * dz / (m_dot * 1000.0)
            h_kJ += dh

        x_e = (h_kJ - h_f_sat) / h_fg_sat
        A_w3 = (2.022 - 0.06238 * P_sys) + \
               (0.1722 - 0.01427 * P_sys) * math.exp((18.177 - 0.5987 * P_sys) * x_e)
        B_w3 = (0.1484 - 1.596 * x_e + 0.1729 * x_e * abs(x_e)) * G_ref / 1000.0 + 1.037
        C_w3 = 1.157 - 0.869 * x_e
        D_w3 = 0.2664 + 0.8357 * math.exp(-124.1 * D_hyd)
        E_w3 = 0.8258 + 0.000794 * (h_f_sat - h_in_kJ)

        q_chf_MW = A_w3 * B_w3 * C_w3 * D_w3 * E_w3
        q_local_MW = qf / 1e6

        if q_local_MW > 1e-6 and i > 5 and i < N - 5:
            dnbr = q_chf_MW / q_local_MW
            if dnbr < min_dnbr:
                min_dnbr = dnbr

    return min_dnbr


def compute_reference_fuel_centerline():
    """Independent computation of peak fuel centerline temperature.

    Uses the conductivity integral method for temperature-dependent UO2
    thermal conductivity: k(T) = 1/(a + b*T_K).
    The integral yields: T_cl = [(a + b*T_fs) * exp(b*q'/(4*pi)) - a] / b
    """
    temps, rhos, cps, mus, ks, hs = load_db_props()

    with open(SPECS_PATH) as f:
        specs = json.load(f)

    q_max = specs['operating_conditions']['peak_linear_heat_rate_kW_m'] * 1e3
    m_dot = specs['operating_conditions']['subchannel_mass_flow_rate_kg_s']
    T_in = specs['operating_conditions']['coolant_inlet_temperature_C']
    L = specs['geometry']['active_fuel_length_m']
    delta = specs['geometry']['extrapolation_distance_m']
    L_e = L + 2 * delta
    D_pin = specs['geometry']['fuel_pin_od_mm'] * 1e-3
    P_p = specs['geometry']['fuel_pin_pitch_mm'] * 1e-3

    r_co = D_pin / 2.0
    r_ci = r_co - specs['geometry']['clad_thickness_mm'] * 1e-3
    k_clad = specs['fuel_properties']['clad_thermal_conductivity_W_mK']
    h_gap = specs['fuel_properties']['gap_conductance_W_m2K']
    a_fuel = specs['fuel_properties']['fuel_conductivity_a_mK_per_W']
    b_fuel = specs['fuel_properties']['fuel_conductivity_b_m_per_W']

    A_f = P_p**2 - math.pi * D_pin**2 / 4.0
    D_hyd = 4.0 * A_f / (math.pi * D_pin)
    G_ref = m_dot / A_f

    N = 200
    dz = L / (N - 1)
    h_kJ = linterp(temps, hs, T_in)
    max_T_fuel = 0.0

    for i in range(N):
        z = i * dz
        zm = z - L / 2.0
        qp = q_max * math.cos(math.pi * zm / L_e)
        qf = qp / (math.pi * D_pin)

        if i > 0:
            zm_prev = (i - 1) * dz - L / 2.0
            qp_prev = q_max * math.cos(math.pi * zm_prev / L_e)
            q_avg = 0.5 * (qp_prev + qp)
            dh = q_avg * dz / (m_dot * 1000.0)
            h_kJ += dh

        T_b = linterp(hs, temps, h_kJ)
        rho = linterp(temps, rhos, T_b)
        cp_J = linterp(temps, cps, T_b) * 1000
        mu = linterp(temps, mus, T_b)
        kw = linterp(temps, ks, T_b)

        Re = G_ref * D_hyd / mu
        Pr = mu * cp_J / kw
        Nu = 0.023 * Re**0.8 * Pr**0.4
        hc = Nu * kw / D_hyd

        T_clad_o = T_b + qf / hc
        dT_clad = qp * math.log(r_co / r_ci) / (2.0 * math.pi * k_clad)
        T_clad_i = T_clad_o + dT_clad
        dT_gap = qp / (2.0 * math.pi * r_ci * h_gap)
        T_fuel_s = T_clad_i + dT_gap

        T_fs_K = T_fuel_s + 273.15
        exponent = b_fuel * qp / (4.0 * math.pi)
        T_cl_K = ((a_fuel + b_fuel * T_fs_K) * math.exp(exponent) - a_fuel) / b_fuel
        T_fuel_cl = T_cl_K - 273.15

        if T_fuel_cl > max_T_fuel:
            max_T_fuel = T_fuel_cl

    return max_T_fuel


# ======== Test Classes ========


class TestDatabaseIntegrity:
    """Verify the SQLite property database is intact and correctly structured."""

    def test_database_exists(self):
        assert os.path.exists(DB_PATH), "coolant.db not found at /app/coolant.db"

    def test_liquid_properties_table_exists(self):
        conn = sqlite3.connect(DB_PATH)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='liquid_properties'"
        ).fetchall()
        conn.close()
        assert len(tables) == 1, "liquid_properties table not found in database"

    def test_property_data_count(self):
        conn = sqlite3.connect(DB_PATH)
        count = conn.execute("SELECT COUNT(*) FROM liquid_properties").fetchone()[0]
        conn.close()
        assert count >= 10, f"Expected at least 10 property rows, got {count}"

    def test_properties_ordered_by_temperature(self):
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT temperature_C FROM liquid_properties ORDER BY rowid"
        ).fetchall()
        conn.close()
        temps = [r[0] for r in rows]
        assert temps == sorted(temps), "Properties should be stored in ascending temperature order"

    def test_property_columns_present(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute("PRAGMA table_info(liquid_properties)")
        cols = {row[1] for row in cursor.fetchall()}
        conn.close()
        required = {'temperature_C', 'density_kg_m3', 'specific_heat_kJ_kgK',
                     'viscosity_Pa_s', 'thermal_conductivity_W_mK', 'enthalpy_kJ_kg'}
        assert required.issubset(cols), f"Missing columns: {required - cols}"


class TestResultsExist:
    """Verify the output file exists with all required fields."""

    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_PATH), "results.json not found at /app/results.json"

    def test_analysis_script_exists(self):
        assert os.path.exists(ANALYSIS_SCRIPT), "analysis.py not found at /app/analysis.py"

    def test_makefile_exists(self):
        assert os.path.exists("/app/Makefile"), "Makefile not found at /app/Makefile"

    def test_all_keys_present(self):
        results = load_results()
        required_keys = [
            "hydraulic_diameter_m",
            "flow_area_m2",
            "mass_flux_kg_m2s",
            "coolant_outlet_temperature_C",
            "peak_cladding_temperature_C",
            "peak_cladding_temperature_location_m",
            "fuel_centerline_temperature_C",
            "fuel_centerline_temperature_location_m",
            "friction_pressure_drop_kPa",
            "form_loss_pressure_drop_kPa",
            "gravity_pressure_drop_kPa",
            "acceleration_pressure_drop_kPa",
            "total_pressure_drop_kPa",
            "minimum_DNBR",
            "minimum_DNBR_location_m",
        ]
        for key in required_keys:
            assert key in results, f"Missing key: {key}"
            assert isinstance(results[key], (int, float)), f"{key} is not numeric"


class TestGeometry:
    """Exact verification of subchannel geometry (simple formulas)."""

    def test_hydraulic_diameter(self):
        results = load_results()
        assert abs(results['hydraulic_diameter_m'] - DH_EXACT) / DH_EXACT < 0.005, \
            f"D_h={results['hydraulic_diameter_m']}, expected={DH_EXACT:.6f}"

    def test_flow_area(self):
        results = load_results()
        assert abs(results['flow_area_m2'] - A_FLOW_EXACT) / A_FLOW_EXACT < 0.005, \
            f"A={results['flow_area_m2']}, expected={A_FLOW_EXACT:.9f}"

    def test_mass_flux(self):
        results = load_results()
        assert abs(results['mass_flux_kg_m2s'] - G_EXACT) / G_EXACT < 0.005, \
            f"G={results['mass_flux_kg_m2s']}, expected={G_EXACT:.1f}"


class TestThermalHydraulics:
    """Verify thermal-hydraulic results within engineering tolerance."""

    def test_outlet_temperature_range(self):
        """Outlet temperature must be between inlet and saturation."""
        results = load_results()
        T_out = results['coolant_outlet_temperature_C']
        assert 292.7 < T_out < 344.8, \
            f"T_out={T_out} outside physical range [292.7, 344.8]"

    def test_outlet_temperature_precision(self):
        """Outlet temperature should match independent 200-node integration within 3 deg C."""
        results = load_results()
        T_out = results['coolant_outlet_temperature_C']
        T_ref = compute_reference_outlet_temp()
        assert abs(T_out - T_ref) < 3.0, \
            f"T_out={T_out:.2f} vs reference={T_ref:.2f}, diff={abs(T_out - T_ref):.2f}"

    def test_total_heat_input(self):
        """Total heat deposited must match analytical chopped-cosine integral."""
        results = load_results()
        with open(SPECS_PATH) as f:
            specs = json.load(f)

        q_max = specs['operating_conditions']['peak_linear_heat_rate_kW_m'] * 1e3
        L = specs['geometry']['active_fuel_length_m']
        delta = specs['geometry']['extrapolation_distance_m']
        L_e = L + 2 * delta
        m_dot = specs['operating_conditions']['subchannel_mass_flow_rate_kg_s']

        Q_analytical = 2 * q_max * L_e / math.pi * math.sin(math.pi * L / (2 * L_e))

        temps, _, _, _, _, hs = load_db_props()
        h_in = linterp(temps, hs, specs['operating_conditions']['coolant_inlet_temperature_C'])
        h_out = linterp(temps, hs, results['coolant_outlet_temperature_C'])
        Q_from_results = m_dot * (h_out - h_in) * 1000.0

        rel_err = abs(Q_from_results - Q_analytical) / Q_analytical
        assert rel_err < 0.03, \
            f"Heat input {Q_from_results:.0f} W vs analytical {Q_analytical:.0f} W (err={rel_err:.3f})"

    def test_peak_clad_temp_above_outlet(self):
        results = load_results()
        assert results['peak_cladding_temperature_C'] > results['coolant_outlet_temperature_C'], \
            "Peak clad temp should exceed outlet coolant temp"

    def test_peak_clad_temp_range(self):
        results = load_results()
        T_clad = results['peak_cladding_temperature_C']
        assert 340 < T_clad < 365, \
            f"Peak T_clad={T_clad} outside expected range [340, 365]"

    def test_peak_clad_temp_precision(self):
        """Peak clad temperature should match independent reference within 3 deg C."""
        results = load_results()
        T_ref = compute_reference_peak_clad()
        assert abs(results['peak_cladding_temperature_C'] - T_ref) < 3.0, \
            f"T_clad={results['peak_cladding_temperature_C']:.1f} vs ref={T_ref:.1f}"

    def test_peak_clad_location_downstream_of_midplane(self):
        """Peak clad temp occurs downstream of core midplane due to rising bulk temp."""
        results = load_results()
        z_peak = results['peak_cladding_temperature_location_m']
        midplane = L_ACTIVE / 2
        assert z_peak > midplane, \
            f"Peak clad location z={z_peak} should be above midplane={midplane}"

    def test_peak_clad_location_range(self):
        results = load_results()
        z_peak = results['peak_cladding_temperature_location_m']
        assert L_ACTIVE * 0.55 < z_peak < L_ACTIVE * 0.90, \
            f"Peak clad at z={z_peak}, expected in [{L_ACTIVE * 0.55:.2f}, {L_ACTIVE * 0.90:.2f}]"


class TestFuelCenterline:
    """Verify fuel centerline temperature calculations."""

    def test_fuel_centerline_above_cladding(self):
        """Fuel centerline must exceed peak cladding temperature."""
        results = load_results()
        assert results['fuel_centerline_temperature_C'] > results['peak_cladding_temperature_C'], \
            "Fuel centerline must exceed peak cladding temperature"

    def test_fuel_centerline_below_melting(self):
        """Fuel centerline must be below UO2 melting point."""
        results = load_results()
        with open(SPECS_PATH) as f:
            specs = json.load(f)
        T_melt = specs['fuel_properties']['fuel_melting_temperature_C']
        assert results['fuel_centerline_temperature_C'] < T_melt, \
            f"Fuel centerline {results['fuel_centerline_temperature_C']} exceeds melting point {T_melt}"

    def test_fuel_centerline_range(self):
        """Fuel centerline temperature must be in physically expected range."""
        results = load_results()
        T_fuel = results['fuel_centerline_temperature_C']
        assert 1300 < T_fuel < 1700, \
            f"Fuel centerline T={T_fuel} outside expected range [1300, 1700]"

    def test_fuel_centerline_precision(self):
        """Fuel centerline temp must match reference with conductivity integral within 10 C."""
        results = load_results()
        T_ref = compute_reference_fuel_centerline()
        diff = abs(results['fuel_centerline_temperature_C'] - T_ref)
        assert diff < 10.0, \
            f"T_fuel_cl={results['fuel_centerline_temperature_C']:.1f} vs ref={T_ref:.1f} (diff={diff:.1f})"

    def test_fuel_centerline_location_downstream(self):
        """Peak fuel centerline location should be near or downstream of midplane."""
        results = load_results()
        z = results['fuel_centerline_temperature_location_m']
        midplane = L_ACTIVE / 2
        assert z >= midplane * 0.90, \
            f"Peak fuel CL location z={z} should be near or downstream of midplane={midplane}"

    def test_fuel_centerline_location_range(self):
        results = load_results()
        z = results['fuel_centerline_temperature_location_m']
        assert L_ACTIVE * 0.40 < z < L_ACTIVE * 0.85, \
            f"Peak fuel CL at z={z}, expected in [{L_ACTIVE * 0.40:.2f}, {L_ACTIVE * 0.85:.2f}]"

    def test_fuel_exceeds_clad_by_gap_contribution(self):
        """Fuel centerline must exceed cladding by more than just cladding+fuel dT.

        If gap thermal resistance is missing, the fuel-to-cladding difference
        will be too small because the gap contributes ~200+ C at peak conditions.
        """
        results = load_results()
        with open(SPECS_PATH) as f:
            specs = json.load(f)

        q_max = specs['operating_conditions']['peak_linear_heat_rate_kW_m'] * 1e3
        r_ci = (specs['geometry']['fuel_pin_od_mm'] / 2.0 - specs['geometry']['clad_thickness_mm']) * 1e-3
        h_gap_val = specs['fuel_properties']['gap_conductance_W_m2K']

        dT_gap_peak = q_max / (2 * math.pi * r_ci * h_gap_val)
        delta_T = results['fuel_centerline_temperature_C'] - results['peak_cladding_temperature_C']
        assert delta_T > dT_gap_peak * 0.8, \
            f"Fuel-to-clad delta={delta_T:.0f} C too small; gap alone should contribute ~{dT_gap_peak:.0f} C"


class TestPressureDrop:
    """Verify pressure drop components."""

    def test_total_pressure_drop_range(self):
        results = load_results()
        dp = results['total_pressure_drop_kPa']
        assert 70 < dp < 200, f"Total dP={dp} kPa outside expected range [70, 200]"

    def test_components_sum_to_total(self):
        results = load_results()
        component_sum = (
            results['friction_pressure_drop_kPa'] +
            results['form_loss_pressure_drop_kPa'] +
            results['gravity_pressure_drop_kPa'] +
            results['acceleration_pressure_drop_kPa']
        )
        total = results['total_pressure_drop_kPa']
        assert abs(component_sum - total) / max(abs(total), 1.0) < 0.02, \
            f"Components sum={component_sum:.2f} != total={total:.2f}"

    def test_friction_sufficient(self):
        results = load_results()
        assert results['friction_pressure_drop_kPa'] > 20, \
            "Friction dP should be > 20 kPa for this geometry and flow rate"

    def test_form_loss_positive(self):
        results = load_results()
        assert results['form_loss_pressure_drop_kPa'] > 10, \
            "Form loss dP from spacer grids should be significant (>10 kPa)"

    def test_gravity_positive(self):
        results = load_results()
        assert results['gravity_pressure_drop_kPa'] > 15, \
            "Gravity dP for ~3.66m of water should be >15 kPa"

    def test_acceleration_positive(self):
        results = load_results()
        assert results['acceleration_pressure_drop_kPa'] > 0, \
            "Acceleration dP should be positive (density decreases with heating)"


class TestDNBR:
    """Verify DNBR calculation."""

    def test_minimum_dnbr_range(self):
        results = load_results()
        mdnbr = results['minimum_DNBR']
        assert 1.0 < mdnbr < 3.5, f"Min DNBR={mdnbr} outside expected range [1.0, 3.5]"

    def test_minimum_dnbr_precision(self):
        """DNBR must match independent reference computation within 10%."""
        results = load_results()
        dnbr_ref = compute_reference_min_dnbr()
        rel_err = abs(results['minimum_DNBR'] - dnbr_ref) / dnbr_ref
        assert rel_err < 0.10, \
            f"DNBR={results['minimum_DNBR']:.3f} vs ref={dnbr_ref:.3f} (err={rel_err:.3f})"

    def test_minimum_dnbr_location_range(self):
        results = load_results()
        z = results['minimum_DNBR_location_m']
        assert L_ACTIVE * 0.40 < z < L_ACTIVE * 0.85, \
            f"MDNBR location z={z} outside expected range"

    def test_dnbr_location_near_or_after_midplane(self):
        """Min DNBR should be at or downstream of midplane."""
        results = load_results()
        z = results['minimum_DNBR_location_m']
        midplane = L_ACTIVE / 2
        assert z >= midplane * 0.90, \
            f"MDNBR location z={z} too far upstream from midplane={midplane}"


class TestMakePipeline:
    """Verify the make-based build pipeline works end-to-end."""

    def test_make_rebuild(self):
        """Verify make clean && make correctly rebuilds results."""
        shutil.copy(RESULTS_PATH, RESULTS_PATH + ".pre_make")
        try:
            result = subprocess.run(
                ['make', '-C', '/app', 'clean'],
                capture_output=True, text=True, timeout=30,
            )
            assert result.returncode == 0, f"make clean failed: {result.stderr}"
            assert not os.path.exists(RESULTS_PATH), "make clean should remove results.json"

            result = subprocess.run(
                ['make', '-C', '/app', 'all'],
                capture_output=True, text=True, timeout=120,
            )
            assert result.returncode == 0, f"make all failed: {result.stderr}"
            assert os.path.exists(RESULTS_PATH), "make all should produce results.json"

            new_results = load_results()
            assert 'minimum_DNBR' in new_results
            assert 'coolant_outlet_temperature_C' in new_results
            assert 'fuel_centerline_temperature_C' in new_results
        finally:
            if os.path.exists(RESULTS_PATH + ".pre_make"):
                shutil.copy(RESULTS_PATH + ".pre_make", RESULTS_PATH)
                os.remove(RESULTS_PATH + ".pre_make")

    def test_make_verify_runs(self):
        """Verify make verify target executes successfully with sqlite3 and jq."""
        result = subprocess.run(
            ['make', '-C', '/app', 'verify'],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"make verify failed: {result.stderr}"
        assert 'minimum_DNBR' in result.stdout or 'DNBR' in result.stdout, \
            "make verify should display DNBR results"


class TestRerunConsistency:
    """Modify input and re-run to verify the implementation is general."""

    def test_reduced_heat_rate_effects(self):
        """Reducing heat rate by 20% should lower T_out, T_clad, T_fuel, raise DNBR."""
        original_results = load_results()

        with open(SPECS_PATH) as f:
            specs = json.load(f)

        shutil.copy(SPECS_PATH, SPECS_PATH + ".bak")
        shutil.copy(RESULTS_PATH, RESULTS_PATH + ".bak")

        try:
            specs['operating_conditions']['peak_linear_heat_rate_kW_m'] *= 0.80
            with open(SPECS_PATH, 'w') as f:
                json.dump(specs, f, indent=2)

            result = subprocess.run(
                ['python3', ANALYSIS_SCRIPT],
                capture_output=True, text=True, timeout=120,
            )
            assert result.returncode == 0, \
                f"analysis.py re-run failed:\nstderr: {result.stderr[-500:]}"

            new_results = load_results()

            assert new_results['coolant_outlet_temperature_C'] < original_results['coolant_outlet_temperature_C'], \
                "Lower heat rate should reduce outlet temperature"
            assert new_results['peak_cladding_temperature_C'] < original_results['peak_cladding_temperature_C'], \
                "Lower heat rate should reduce peak cladding temperature"
            assert new_results['fuel_centerline_temperature_C'] < original_results['fuel_centerline_temperature_C'], \
                "Lower heat rate should reduce fuel centerline temperature"
            assert new_results['minimum_DNBR'] > original_results['minimum_DNBR'], \
                "Lower heat rate should increase DNBR (safer)"

            assert abs(new_results['hydraulic_diameter_m'] - original_results['hydraulic_diameter_m']) < 1e-9, \
                "Geometry should not change with heat rate"
            assert abs(new_results['mass_flux_kg_m2s'] - original_results['mass_flux_kg_m2s']) < 0.01, \
                "Mass flux should not change with heat rate"

        finally:
            shutil.copy(SPECS_PATH + ".bak", SPECS_PATH)
            shutil.copy(RESULTS_PATH + ".bak", RESULTS_PATH)
            for bak in [SPECS_PATH + ".bak", RESULTS_PATH + ".bak"]:
                if os.path.exists(bak):
                    os.remove(bak)
