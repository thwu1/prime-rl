#!/usr/bin/env python3
"""
PWR Hot Channel Thermal-Hydraulic Safety Analysis - Corrected

"""

import json
import math
import sqlite3

# ---- Read input data ----
with open('/app/reactor_specs.json') as f:
    specs = json.load(f)

geo = specs['geometry']
ops = specs['operating_conditions']
sat = specs['saturation_properties']
fuel = specs['fuel_properties']

D = geo['fuel_pin_od_mm'] * 1e-3
P_pitch = geo['fuel_pin_pitch_mm'] * 1e-3
L = geo['active_fuel_length_m']
delta = geo['extrapolation_distance_m']
N_grids = geo['num_spacer_grids']
K_grid = geo['spacer_grid_loss_coefficient']

P_sys = ops['system_pressure_MPa']
T_in_C = ops['coolant_inlet_temperature_C']
m_dot = ops['subchannel_mass_flow_rate_kg_s']
q_prime_max = ops['peak_linear_heat_rate_kW_m'] * 1e3

T_sat = sat['temperature_C']
h_f = sat['liquid_enthalpy_kJ_kg']
h_fg = sat['latent_heat_kJ_kg']

# ---- Read water properties from SQLite database ----
prop_T, prop_rho, prop_cp, prop_mu, prop_k, prop_h = [], [], [], [], [], []
conn = sqlite3.connect('/app/coolant.db')
rows = conn.execute(
    "SELECT temperature_C, density_kg_m3, specific_heat_kJ_kgK, "
    "viscosity_Pa_s, thermal_conductivity_W_mK, enthalpy_kJ_kg "
    "FROM liquid_properties ORDER BY temperature_C"
).fetchall()
conn.close()

for row in rows:
    prop_T.append(row[0])
    prop_rho.append(row[1])
    prop_cp.append(row[2])
    prop_mu.append(row[3])
    prop_k.append(row[4])
    prop_h.append(row[5])


def interp(x_arr, y_arr, x):
    if x <= x_arr[0]:
        return y_arr[0]
    if x >= x_arr[-1]:
        return y_arr[-1]
    for i in range(len(x_arr) - 1):
        if x_arr[i] <= x <= x_arr[i + 1]:
            frac = (x - x_arr[i]) / (x_arr[i + 1] - x_arr[i])
            return y_arr[i] + frac * (y_arr[i + 1] - y_arr[i])
    return y_arr[-1]


def get_props(T_C):
    return {
        'rho': interp(prop_T, prop_rho, T_C),
        'cp': interp(prop_T, prop_cp, T_C) * 1000,
        'mu': interp(prop_T, prop_mu, T_C),
        'k': interp(prop_T, prop_k, T_C),
        'h_kJ': interp(prop_T, prop_h, T_C),
    }


def temp_from_enthalpy(h_kJ_kg):
    if h_kJ_kg <= prop_h[0]:
        return prop_T[0]
    if h_kJ_kg >= prop_h[-1]:
        return prop_T[-1]
    for i in range(len(prop_h) - 1):
        if prop_h[i] <= h_kJ_kg <= prop_h[i + 1]:
            frac = (h_kJ_kg - prop_h[i]) / (prop_h[i + 1] - prop_h[i])
            return prop_T[i] + frac * (prop_T[i + 1] - prop_T[i])
    return prop_T[-1]


# ==== Step 1: Subchannel Geometry ====
A_flow = P_pitch**2 - math.pi * D**2 / 4.0
P_w = math.pi * D
D_h = 4.0 * A_flow / P_w
G = m_dot / A_flow

# ==== Step 2: Axial discretization ====
L_e = L + 2.0 * delta
N_nodes = 500
dz = L / (N_nodes - 1)
z = [i * dz for i in range(N_nodes)]
z_mid = [zi - L / 2.0 for zi in z]

# FIX 1: Use extrapolated length L_e in denominator (not active length L)
q_prime = [q_prime_max * math.cos(math.pi * zm / L_e) for zm in z_mid]
# FIX 2: Surface heat flux uses pin OD D (not hydraulic diameter D_h)
q_flux = [qp / (math.pi * D) for qp in q_prime]

# ==== Step 3: Enthalpy and temperature distribution ====
h_in_kJ = get_props(T_in_C)['h_kJ']

h_z = [0.0] * N_nodes
T_bulk = [0.0] * N_nodes
h_z[0] = h_in_kJ
T_bulk[0] = T_in_C

for i in range(1, N_nodes):
    q_avg = 0.5 * (q_prime[i - 1] + q_prime[i])
    dh_kJ = q_avg * dz / (m_dot * 1000.0)
    h_z[i] = h_z[i - 1] + dh_kJ
    T_bulk[i] = temp_from_enthalpy(h_z[i])

T_out = T_bulk[-1]

# ==== Step 4: Heat transfer and cladding temperature ====
h_conv = [0.0] * N_nodes
T_clad = [0.0] * N_nodes

for i in range(N_nodes):
    props = get_props(T_bulk[i])
    rho = props['rho']
    cp = props['cp']
    mu = props['mu']
    k_w = props['k']

    Re = G * D_h / mu
    Pr = mu * cp / k_w
    Nu = 0.023 * Re**0.8 * Pr**0.4
    hc = Nu * k_w / D_h
    h_conv[i] = hc
    T_clad[i] = T_bulk[i] + q_flux[i] / hc

peak_clad_idx = 0
peak_clad_temp = T_clad[0]
for i in range(1, N_nodes):
    if T_clad[i] > peak_clad_temp:
        peak_clad_temp = T_clad[i]
        peak_clad_idx = i
peak_clad_z = z[peak_clad_idx]

# ==== Step 4b: Fuel centerline temperature ====
r_co = D / 2.0
r_ci = r_co - geo['clad_thickness_mm'] * 1e-3
k_clad_val = fuel['clad_thermal_conductivity_W_mK']
r_fuel = geo['fuel_pellet_od_mm'] * 1e-3 / 2.0
# FIX 5: Use temperature-dependent conductivity model coefficients
h_gap = fuel['gap_conductance_W_m2K']
a_fuel = fuel['fuel_conductivity_a_mK_per_W']
b_fuel = fuel['fuel_conductivity_b_m_per_W']

T_fuel_cl = [0.0] * N_nodes
for i in range(N_nodes):
    dT_clad_wall = q_prime[i] * math.log(r_co / r_ci) / (2.0 * math.pi * k_clad_val)
    T_ci = T_clad[i] + dT_clad_wall

    # FIX 6: Add gap thermal resistance
    dT_gap = q_prime[i] / (2.0 * math.pi * r_ci * h_gap)
    T_fuel_surface = T_ci + dT_gap

    # FIX 5: Conductivity integral method for k(T) = 1/(a + b*T_K)
    T_fs_K = T_fuel_surface + 273.15
    exponent = b_fuel * q_prime[i] / (4.0 * math.pi)
    T_cl_K = ((a_fuel + b_fuel * T_fs_K) * math.exp(exponent) - a_fuel) / b_fuel
    T_fuel_cl[i] = T_cl_K - 273.15

fuel_cl_idx = 0
fuel_cl_temp = T_fuel_cl[0]
for i in range(1, N_nodes):
    if T_fuel_cl[i] > fuel_cl_temp:
        fuel_cl_temp = T_fuel_cl[i]
        fuel_cl_idx = i
fuel_cl_z = z[fuel_cl_idx]

# ==== Step 5: Pressure drop ====

# 5a. Frictional pressure drop
dp_friction = 0.0
for i in range(N_nodes - 1):
    T_avg = 0.5 * (T_bulk[i] + T_bulk[i + 1])
    props = get_props(T_avg)
    rho = props['rho']
    mu = props['mu']
    Re = G * D_h / mu
    # FIX 3: Darcy-Blasius friction factor (0.184) not Fanning (0.046)
    f_darcy = 0.184 * Re**(-0.2)
    dp_friction += f_darcy * dz / D_h * G**2 / (2.0 * rho)

# 5b. Form losses (spacer grids uniformly distributed)
dp_form = 0.0
for ig in range(N_grids):
    zg = L * (ig + 1) / (N_grids + 1)
    idx = min(range(N_nodes), key=lambda j: abs(z[j] - zg))
    props = get_props(T_bulk[idx])
    rho = props['rho']
    dp_form += K_grid * G**2 / (2.0 * rho)

# 5c. Gravity (vertical upflow)
dp_gravity = 0.0
for i in range(N_nodes - 1):
    T_avg = 0.5 * (T_bulk[i] + T_bulk[i + 1])
    props = get_props(T_avg)
    rho = props['rho']
    # FIX 4: Positive for vertical upflow (+=, not -=)
    dp_gravity += rho * 9.81 * dz

# 5d. Acceleration
rho_in = get_props(T_in_C)['rho']
rho_out = get_props(T_out)['rho']
dp_accel = G**2 * (1.0 / rho_out - 1.0 / rho_in)

total_dp = dp_friction + dp_form + dp_gravity + dp_accel

# ==== Step 6: W-3 CHF correlation and DNBR ====
DNBR = [0.0] * N_nodes

for i in range(N_nodes):
    x_e = (h_z[i] - h_f) / h_fg

    A_w3 = (2.022 - 0.06238 * P_sys) + \
           (0.1722 - 0.01427 * P_sys) * math.exp((18.177 - 0.5987 * P_sys) * x_e)
    B_w3 = (0.1484 - 1.596 * x_e + 0.1729 * x_e * abs(x_e)) * G / 1000.0 + 1.037
    C_w3 = 1.157 - 0.869 * x_e
    D_w3 = 0.2664 + 0.8357 * math.exp(-124.1 * D_h)
    # FIX 7: Correct subcooling sign: (h_f - h_in) not (h_in - h_f)
    E_w3 = 0.8258 + 0.000794 * (h_f - h_in_kJ)

    q_chf_MW = A_w3 * B_w3 * C_w3 * D_w3 * E_w3

    q_local_MW = q_flux[i] / 1e6
    if q_local_MW > 1e-6:
        DNBR[i] = q_chf_MW / q_local_MW
    else:
        DNBR[i] = 999.0

margin = max(5, N_nodes // 50)
min_dnbr = DNBR[margin]
min_dnbr_idx = margin
for i in range(margin, N_nodes - margin):
    if DNBR[i] < min_dnbr:
        min_dnbr = DNBR[i]
        min_dnbr_idx = i
min_dnbr_z = z[min_dnbr_idx]

# ==== Output ====
results = {
    "hydraulic_diameter_m": round(D_h, 6),
    "flow_area_m2": round(A_flow, 9),
    "mass_flux_kg_m2s": round(G, 1),
    "coolant_outlet_temperature_C": round(T_out, 2),
    "peak_cladding_temperature_C": round(peak_clad_temp, 2),
    "peak_cladding_temperature_location_m": round(peak_clad_z, 3),
    "fuel_centerline_temperature_C": round(fuel_cl_temp, 2),
    "fuel_centerline_temperature_location_m": round(fuel_cl_z, 3),
    "friction_pressure_drop_kPa": round(dp_friction / 1000.0, 2),
    "form_loss_pressure_drop_kPa": round(dp_form / 1000.0, 2),
    "gravity_pressure_drop_kPa": round(dp_gravity / 1000.0, 2),
    "acceleration_pressure_drop_kPa": round(dp_accel / 1000.0, 2),
    "total_pressure_drop_kPa": round(total_dp / 1000.0, 2),
    "minimum_DNBR": round(min_dnbr, 4),
    "minimum_DNBR_location_m": round(min_dnbr_z, 3),
}

with open('/app/results.json', 'w') as f:
    json.dump(results, f, indent=2)

print("Analysis complete. Results written to /app/results.json")
for key, val in results.items():
    print(f"  {key}: {val}")
