#!/usr/bin/env python3
"""IEC 60193 Model-to-Prototype Transposition Pipeline.

Computes specific hydraulic energy, dimensionless coefficients, efficiency
step-up, cavitation analysis, and prototype transposition per IEC 60193
for Francis turbine model acceptance tests.
"""

import csv
import json
import math
import os
import sqlite3
import subprocess

G = 9.80665  # gravitational acceleration [m/s^2]


def load_water_properties(path):
    """Load water properties lookup table, sorted by temperature."""
    table = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            table.append({
                'temp': float(row['temp_C']),
                'rho': float(row['density_kgm3']),
                'nu': float(row['kinematic_viscosity_m2s']),
                'pv': float(row['vapor_pressure_Pa'])
            })
    table.sort(key=lambda x: x['temp'])
    return table


def interp_prop(table, temp, key):
    """Linearly interpolate a water property at the given temperature."""
    if temp <= table[0]['temp']:
        return table[0][key]
    if temp >= table[-1]['temp']:
        return table[-1][key]
    for i in range(len(table) - 1):
        t0, t1 = table[i]['temp'], table[i + 1]['temp']
        if t0 <= temp <= t1:
            frac = (temp - t0) / (t1 - t0)
            return table[i][key] + frac * (table[i + 1][key] - table[i][key])
    return table[-1][key]


def barometric_pressure(altitude_m):
    """Atmospheric pressure at altitude via standard barometric formula."""
    return 101325.0 * (1.0 - 2.2557e-5 * altitude_m) ** 5.2559


def generate_hill_chart(results, output_path):
    """Generate SVG hill chart using gnuplot."""
    data_path = '/tmp/hill_data.dat'
    script_path = '/tmp/hill_chart.gp'

    with open(data_path, 'w') as f:
        f.write("# nED QED eta_prototype\n")
        for r in results:
            f.write(f"{r['nED']:.8f} {r['QED']:.8f} {r['eta_prototype']:.8f}\n")

    script = f"""set terminal svg enhanced size 800,600
set output '{output_path}'
set xlabel 'n_{{ED}} [-]'
set ylabel 'Q_{{ED}} [-]'
set title 'Francis Turbine Prototype Efficiency Hill Chart (IEC 60193)'
set palette defined (0.88 "blue", 0.91 "cyan", 0.93 "green", 0.945 "red")
set cblabel '{{/Symbol h}}_{{prototype}}'
set pointsize 2
set key off
plot '{data_path}' using 1:2:3 with points palette pt 7 ps 3 notitle
"""

    with open(script_path, 'w') as f:
        f.write(script)

    subprocess.run(['gnuplot', script_path], check=True)


def write_sqlite_results(results, bep, prototype_bep, cavitation, db_path):
    """Write results to a SQLite database."""
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute('''CREATE TABLE operating_points (
        point_id INTEGER,
        E_Jkg REAL,
        nED REAL,
        QED REAL,
        TED REAL,
        eta_model REAL,
        Re_model REAL,
        Re_prototype REAL,
        delta_eta REAL,
        eta_prototype REAL,
        sigma_model REAL,
        f_eta_pct REAL
    )''')

    for r in results:
        c.execute('INSERT INTO operating_points VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                  (r['point_id'], r['E_Jkg'], r['nED'], r['QED'], r['TED'],
                   r['eta_model'], r['Re_model'], r['Re_prototype'],
                   r['delta_eta'], r['eta_prototype'], r['sigma_model'],
                   r['f_eta_pct']))

    c.execute('''CREATE TABLE bep_summary (
        point_id INTEGER,
        eta_prototype REAL,
        nED REAL,
        QED REAL,
        Q_m3s REAL,
        n_rpm REAL,
        P_MW REAL
    )''')

    c.execute('INSERT INTO bep_summary VALUES (?,?,?,?,?,?,?)',
              (bep['point_id'], bep['eta_prototype'],
               bep['nED'], bep['QED'],
               prototype_bep['Q_m3s'], prototype_bep['n_rpm'],
               prototype_bep['P_MW']))

    c.execute('''CREATE TABLE cavitation (
        p_atm_Pa REAL,
        p_vapor_Pa REAL,
        sigma_plant REAL,
        sigma_critical REAL,
        safety_margin REAL,
        is_safe INTEGER
    )''')

    c.execute('INSERT INTO cavitation VALUES (?,?,?,?,?,?)',
              (cavitation['p_atm_Pa'], cavitation['p_vapor_Pa'],
               cavitation['sigma_plant'], cavitation['sigma_critical'],
               cavitation['safety_margin'],
               1 if cavitation['is_safe'] else 0))

    conn.commit()
    conn.close()


def main():
    data_dir = '/app/data'
    output_dir = '/app/output'
    json_path = os.path.join(output_dir, 'results.json')
    db_path = os.path.join(output_dir, 'results.db')
    chart_path = os.path.join(output_dir, 'hill_chart.svg')

    # --- Load inputs ---
    with open(os.path.join(data_dir, 'site_config.json')) as f:
        cfg = json.load(f)

    wp = load_water_properties(os.path.join(data_dir, 'water_properties.csv'))

    model_points = []
    with open(os.path.join(data_dir, 'model_tests.csv')) as f:
        reader = csv.DictReader(f)
        for row in reader:
            model_points.append({
                'point_id': int(row['point_id']),
                'gvo_pct': float(row['gvo_pct']),
                'n_rpm': float(row['n_rpm']),
                'p1_kPa': float(row['p1_kPa']),
                'p2_kPa': float(row['p2_kPa']),
                'Q_ls': float(row['Q_ls']),
                'T_Nm': float(row['T_Nm']),
                'water_temp_C': float(row['water_temp_C'])
            })

    # --- Extract configuration ---
    D_M = cfg['model']['D_m']
    A1 = cfg['model']['A1_m2']
    A2 = cfg['model']['A2_m2']
    dz = cfg['model']['z1_minus_z2_m']
    lab_alt = cfg['model']['lab_altitude_m']
    h_s = cfg['model']['submergence_m']

    D_P = cfg['prototype']['D_m']
    E_P = cfg['prototype']['E_Jkg']

    site_alt = cfg['site']['altitude_masl']
    site_temp = cfg['site']['water_temp_C']
    z_tw = cfg['site']['z_tailwater_m']
    z_ref = cfg['site']['z_turbine_ref_m']

    f_Q = cfg['uncertainty']['f_Q_pct']
    f_E = cfg['uncertainty']['f_E_pct']
    f_T = cfg['uncertainty']['f_T_pct']
    f_n = cfg['uncertainty']['f_n_pct']

    sigma_critical = cfg['sigma_critical']

    # --- Prototype water properties ---
    rho_P = interp_prop(wp, site_temp, 'rho')
    nu_P = interp_prop(wp, site_temp, 'nu')
    pv_P = interp_prop(wp, site_temp, 'pv')

    # Prototype Reynolds number
    Re_P = D_P * math.sqrt(2.0 * E_P) / nu_P

    # Atmospheric pressures
    p_atm_lab = barometric_pressure(lab_alt)
    p_atm_site = barometric_pressure(site_alt)

    # --- Process each operating point ---
    results = []
    for pt in model_points:
        temp = pt['water_temp_C']
        rho = interp_prop(wp, temp, 'rho')
        nu = interp_prop(wp, temp, 'nu')
        pv = interp_prop(wp, temp, 'pv')

        Q = pt['Q_ls'] / 1000.0
        n = pt['n_rpm'] / 60.0
        p1 = pt['p1_kPa'] * 1000.0
        p2 = pt['p2_kPa'] * 1000.0
        T = pt['T_Nm']

        c1 = Q / A1
        c2 = Q / A2

        E = (p1 - p2) / rho + (c1**2 - c2**2) / 2.0 + G * dz

        sqrt_E = math.sqrt(E)
        nED = n * D_M / sqrt_E
        QED = Q / (D_M**2 * sqrt_E)
        TED = T / (rho * D_M**3 * E)

        omega = 2.0 * math.pi * n
        P_mech = T * omega
        eta_model = P_mech / (rho * Q * E)

        Re_model = D_M * math.sqrt(2.0 * E) / nu

        delta_eta = (1.0 - eta_model) * (1.0 - (Re_model / Re_P) ** 0.16)
        eta_prototype = eta_model + delta_eta

        NPSE = (p_atm_lab - pv) / rho + G * h_s
        sigma_model = NPSE / E

        f_eta_pct = math.sqrt(f_T**2 + f_n**2 + f_Q**2 + f_E**2)

        results.append({
            'point_id': pt['point_id'],
            'E_Jkg': E,
            'nED': nED,
            'QED': QED,
            'TED': TED,
            'eta_model': eta_model,
            'Re_model': Re_model,
            'Re_prototype': Re_P,
            'delta_eta': delta_eta,
            'eta_prototype': eta_prototype,
            'sigma_model': sigma_model,
            'f_eta_pct': f_eta_pct
        })

    # --- BEP identification ---
    bep = max(results, key=lambda x: x['eta_prototype'])
    bep_model_pt = next(p for p in model_points
                        if p['point_id'] == bep['point_id'])

    # --- Prototype transposition at BEP ---
    Q_M_bep = bep_model_pt['Q_ls'] / 1000.0
    n_M_bep = bep_model_pt['n_rpm'] / 60.0
    E_M_bep = bep['E_Jkg']

    scale_D = D_P / D_M
    scale_E_sqrt = math.sqrt(E_P / E_M_bep)

    Q_P = Q_M_bep * scale_D**2 * scale_E_sqrt
    n_P = n_M_bep * (1.0 / scale_D) * scale_E_sqrt
    P_P = rho_P * Q_P * E_P * bep['eta_prototype']

    # --- Cavitation safety analysis ---
    sigma_plant = ((p_atm_site - pv_P) / rho_P + G * (z_tw - z_ref)) / E_P
    safety_margin = sigma_plant - sigma_critical
    is_safe = safety_margin >= 0.05

    # --- Build output dicts ---
    bep_dict = {
        'point_id': bep['point_id'],
        'eta_prototype': bep['eta_prototype'],
        'nED': bep['nED'],
        'QED': bep['QED']
    }

    proto_dict = {
        'Q_m3s': Q_P,
        'n_rpm': n_P * 60.0,
        'P_MW': P_P / 1e6
    }

    cav_dict = {
        'p_atm_Pa': p_atm_site,
        'p_vapor_Pa': pv_P,
        'sigma_plant': sigma_plant,
        'sigma_critical': sigma_critical,
        'safety_margin': safety_margin,
        'is_safe': is_safe
    }

    output = {
        'points': results,
        'bep': bep_dict,
        'prototype_bep': proto_dict,
        'cavitation': cav_dict
    }

    # --- Write JSON output ---
    os.makedirs(output_dir, exist_ok=True)
    with open(json_path, 'w') as f:
        json.dump(output, f, indent=2)

    # --- Generate gnuplot hill chart ---
    generate_hill_chart(results, chart_path)

    # --- Write SQLite results database ---
    write_sqlite_results(results, bep_dict, proto_dict, cav_dict, db_path)


if __name__ == '__main__':
    main()
