#!/usr/bin/env python3
"""
Thermodynamic property prediction engine for CO2.
Reads NIST WebBook isothermal data and critical property measurements,
computes equation of state properties, stores data in SQLite, and validates.
"""

import csv
import json
import math
import os
import sqlite3
from html.parser import HTMLParser

R = 0.08314472  # L-bar/(mol-K)

TC = 0.0
PC = 0.0
OMEGA = 0.0
KAPPA = 0.0
A0 = 0.0
B_CONST = 0.0


def parse_critical_measurements(filepath):
    measurements = {}
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['fluid'].strip() != 'CO2':
                continue
            prop = row['property'].strip()
            val = float(row['value'])
            unc_str = row.get('uncertainty', '').strip()
            unc = float(unc_str) if unc_str else 1.0
            if prop not in measurements:
                measurements[prop] = []
            measurements[prop].append((val, unc))

    result = {}
    for prop, data in measurements.items():
        if len(data) == 1:
            result[prop] = data[0][0]
        else:
            weights = [1.0 / (u ** 2) for _, u in data]
            total_w = sum(weights)
            result[prop] = sum(v * w for (v, _), w in zip(data, weights)) / total_w

    return result


class NistSaturationParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.current_row = []
        self.rows = []
        self.header_done = False
        self.cell_text = ""

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self.in_table = True
        elif tag == 'tr' and self.in_table:
            self.in_row = True
            self.current_row = []
        elif tag in ('td', 'th') and self.in_row:
            self.in_cell = True
            self.cell_text = ""

    def handle_endtag(self, tag):
        if tag == 'table':
            self.in_table = False
        elif tag == 'tr' and self.in_row:
            self.in_row = False
            if self.header_done:
                self.rows.append(self.current_row)
            else:
                self.header_done = True
        elif tag in ('td', 'th') and self.in_cell:
            self.in_cell = False
            self.current_row.append(self.cell_text.strip())

    def handle_data(self, data):
        if self.in_cell:
            self.cell_text += data

    def handle_entityref(self, name):
        if self.in_cell:
            entity_map = {'nbsp': ' ', 'middot': '.', 'deg': ' ',
                          'sub': '', 'lt': '<', 'gt': '>'}
            self.cell_text += entity_map.get(name, '')


def parse_saturation_html(filepath):
    with open(filepath) as f:
        html = f.read()
    parser = NistSaturationParser()
    parser.feed(html)

    data = []
    for row in parser.rows:
        if len(row) >= 2:
            try:
                t = float(row[0])
                p = float(row[1])
                data.append({'T_K': t, 'P_sat_bar': p})
            except (ValueError, IndexError):
                continue
    return data


def init_eos_params(crit):
    global TC, PC, OMEGA, KAPPA, A0, B_CONST
    TC = crit['Tc']
    PC = crit['Pc']
    OMEGA = crit['omega']
    KAPPA = 0.37464 + 1.54226 * OMEGA - 0.26992 * OMEGA ** 2
    A0 = 0.45724 * R ** 2 * TC ** 2 / PC
    B_CONST = 0.07780 * R * TC / PC


def pr_alpha(T):
    return (1.0 + KAPPA * (1.0 - math.sqrt(T / TC))) ** 2


def pr_a(T):
    return A0 * pr_alpha(T)


def pr_AB(T, P):
    a = pr_a(T)
    A = a * P / (R * T) ** 2
    B = B_CONST * P / (R * T)
    return A, B


def cube_root(x):
    if x >= 0:
        return x ** (1.0 / 3.0)
    return -((-x) ** (1.0 / 3.0))


def solve_cubic_pr(T, P):
    A, B = pr_AB(T, P)
    c2 = -(1.0 - B)
    c1 = A - 3.0 * B ** 2 - 2.0 * B
    c0 = -(A * B - B ** 2 - B ** 3)

    p = c1 - c2 ** 2 / 3.0
    q = c0 - c2 * c1 / 3.0 + 2.0 * c2 ** 3 / 27.0

    disc = q ** 2 / 4.0 + p ** 3 / 27.0

    roots = []
    if disc > 1e-14:
        sd = math.sqrt(disc)
        u = cube_root(-q / 2.0 + sd)
        v = cube_root(-q / 2.0 - sd)
        roots = [u + v - c2 / 3.0]
    elif disc < -1e-14:
        r = math.sqrt(-p ** 3 / 27.0)
        cos_arg = max(-1.0, min(1.0, -q / (2.0 * r)))
        theta = math.acos(cos_arg)
        m = 2.0 * math.sqrt(-p / 3.0)
        roots = [
            m * math.cos(theta / 3.0) - c2 / 3.0,
            m * math.cos((theta + 2.0 * math.pi) / 3.0) - c2 / 3.0,
            m * math.cos((theta + 4.0 * math.pi) / 3.0) - c2 / 3.0,
        ]
    else:
        if abs(q) < 1e-15:
            roots = [-c2 / 3.0]
        else:
            u = cube_root(-q / 2.0)
            roots = [2.0 * u - c2 / 3.0, -u - c2 / 3.0]

    real_roots = sorted([z for z in roots if z > B])
    return real_roots, A, B


def ln_fugacity_coeff(Z, A, B):
    s2 = math.sqrt(2.0)
    arg_num = Z + (1.0 + s2) * B
    arg_den = Z + (1.0 - s2) * B
    if arg_num <= 0 or arg_den <= 0 or (Z - B) <= 0:
        return float('nan')
    return (Z - 1.0) - math.log(Z - B) - A / (2.0 * s2 * B) * math.log(arg_num / arg_den)


def departure_enthalpy_kj(T, P, Z, A, B):
    a = pr_a(T)
    alpha = pr_alpha(T)
    sqrt_alpha = math.sqrt(alpha)
    dalpha_dT = -KAPPA * sqrt_alpha / math.sqrt(T * TC)
    da_dT = A0 * dalpha_dT

    s2 = math.sqrt(2.0)
    ln_term = math.log(
        (Z + (1.0 + s2) * B) / (Z + (1.0 - s2) * B)
    )

    h_dep = R * T * (Z - 1.0) + (T * da_dT - a) / (2.0 * s2 * B_CONST) * ln_term
    return h_dep * 0.1


def select_root(roots, phase):
    if len(roots) == 1:
        return roots[0]
    if phase == "liquid":
        return min(roots)
    return max(roots)


def parse_nist_tsv(filepath):
    data = []
    with open(filepath) as f:
        f.readline()
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split('\t')
            if len(parts) < 14:
                continue
            T = float(parts[0])
            P = float(parts[1])
            V = float(parts[3])
            phase = parts[13].strip()
            Z_nist = P * V / (R * T)
            data.append({
                'T': T, 'P': P, 'V': V,
                'phase': phase, 'Z_NIST': Z_nist
            })
    return data


def compute_compressibility():
    result = {}
    for T_str, fname in [('250', 'co2_250K.tsv'), ('300', 'co2_300K.tsv'),
                          ('350', 'co2_350K.tsv'), ('400', 'co2_400K.tsv')]:
        data = parse_nist_tsv(os.path.join('/app/data', fname))
        seen = set()
        entries = []
        for d in data:
            key = round(d['P'], 4)
            if key in seen:
                continue
            seen.add(key)
            roots, A, B = solve_cubic_pr(d['T'], d['P'])
            if not roots:
                continue
            Z_pr = select_root(roots, d['phase'])
            entries.append({
                'P_bar': d['P'],
                'Z_PR': round(Z_pr, 6),
                'Z_NIST': round(d['Z_NIST'], 6),
                'phase': d['phase']
            })
        result[T_str] = entries
    return result


def compute_fugacity(state_points):
    result = []
    for T, P in state_points:
        roots, A, B = solve_cubic_pr(T, P)
        Z = max(roots)
        lnphi = ln_fugacity_coeff(Z, A, B)
        result.append({
            'T_K': T,
            'P_bar': P,
            'ln_phi': round(lnphi, 6)
        })
    return result


def compute_departure_enthalpy(state_points):
    result = []
    for T, P in state_points:
        roots, A, B = solve_cubic_pr(T, P)
        Z = max(roots)
        hdep = departure_enthalpy_kj(T, P, Z, A, B)
        result.append({
            'T_K': T,
            'P_bar': P,
            'H_dep_kJ_per_mol': round(hdep, 6)
        })
    return result


def compute_second_virial():
    result = []
    for T_val, fname in [(250, 'co2_250K.tsv'), (300, 'co2_300K.tsv'),
                          (350, 'co2_350K.tsv'), (400, 'co2_400K.tsv')]:
        data = parse_nist_tsv(os.path.join('/app/data', fname))
        d0 = data[0]
        Z = d0['Z_NIST']
        V = d0['V']
        B_data = (Z - 1.0) * V * 1000.0

        a = pr_a(T_val)
        B_pr = (B_CONST - a / (R * T_val)) * 1000.0

        result.append({
            'T_K': T_val,
            'B_data_cm3_per_mol': round(B_data, 4),
            'B_PR_cm3_per_mol': round(B_pr, 4)
        })
    return result


def find_psat(T):
    if T >= TC:
        return float('nan')

    P_lo = 5.5
    P_hi = PC - 0.5

    for _ in range(200):
        P_mid = (P_lo + P_hi) / 2.0
        roots, A, B = solve_cubic_pr(T, P_mid)

        if len(roots) < 2:
            Z = roots[0] if roots else 0.5
            if Z > 0.5:
                P_lo = P_mid
            else:
                P_hi = P_mid
            continue

        Z_vap = max(roots)
        Z_liq = min(roots)

        if abs(Z_vap - Z_liq) < 1e-10:
            break

        lnphi_v = ln_fugacity_coeff(Z_vap, A, B)
        lnphi_l = ln_fugacity_coeff(Z_liq, A, B)

        if math.isnan(lnphi_v) or math.isnan(lnphi_l):
            P_hi = P_mid
            continue

        diff = lnphi_l - lnphi_v

        if abs(diff) < 1e-12:
            break

        if diff > 0:
            P_lo = P_mid
        else:
            P_hi = P_mid

    return round(P_mid, 4)


def compute_vle():
    result = []
    for T in [280, 290]:
        psat = find_psat(T)
        result.append({
            'T_K': T,
            'P_sat_bar': psat
        })
    return result


def compute_compression_work():
    T = 350.0
    P1 = 1.0
    P2 = 80.0

    W_ideal = R * T * math.log(P2 / P1) * 0.1

    roots1, A1, B1 = solve_cubic_pr(T, P1)
    Z1 = max(roots1)
    lnphi1 = ln_fugacity_coeff(Z1, A1, B1)
    f1 = P1 * math.exp(lnphi1)

    roots2, A2, B2 = solve_cubic_pr(T, P2)
    Z2 = max(roots2)
    lnphi2 = ln_fugacity_coeff(Z2, A2, B2)
    f2 = P2 * math.exp(lnphi2)

    W_real = R * T * math.log(f2 / f1) * 0.1

    return {
        'T_K': 350,
        'P1_bar': P1,
        'P2_bar': P2,
        'W_ideal_kJ_per_mol': round(W_ideal, 6),
        'W_real_kJ_per_mol': round(W_real, 6)
    }


def compute_model_accuracy(compressibility, saturation_data, vle_prediction):
    result = {}

    comp_rmse = {}
    for t_str, entries in compressibility.items():
        z_errors_sq = [(e['Z_PR'] - e['Z_NIST']) ** 2 for e in entries]
        abs_errors = [abs(e['Z_PR'] - e['Z_NIST']) for e in entries]
        n = len(entries)
        rmse = math.sqrt(sum(z_errors_sq) / n) if n > 0 else 0
        comp_rmse[t_str] = {
            'rmse': round(rmse, 6),
            'max_abs_error': round(max(abs_errors), 6) if abs_errors else 0,
            'n_points': n
        }
    result['compressibility_rmse'] = comp_rmse

    sat_val = []
    for vle in vle_prediction:
        T = vle['T_K']
        p_pred = vle['P_sat_bar']
        closest = min(saturation_data, key=lambda d: abs(d['T_K'] - T))
        p_nist = closest['P_sat_bar']
        rel_err = (p_pred - p_nist) / p_nist
        sat_val.append({
            'T_K': T,
            'P_sat_nist_bar': round(p_nist, 4),
            'P_sat_predicted_bar': round(p_pred, 4),
            'relative_error': round(rel_err, 6)
        })
    result['saturation_validation'] = sat_val

    return result


def create_database(all_raw_data, critical_csv_path, saturation_data):
    """Create and populate the SQLite database with all parsed reference data."""
    conn = sqlite3.connect('/app/thermo.db')
    c = conn.cursor()

    c.execute('DROP TABLE IF EXISTS nist_isotherms')
    c.execute('DROP TABLE IF EXISTS critical_props')
    c.execute('DROP TABLE IF EXISTS saturation_ref')

    c.execute('''CREATE TABLE nist_isotherms (
        temperature_K REAL,
        pressure_bar REAL,
        volume_L_mol REAL,
        phase TEXT
    )''')

    c.execute('''CREATE TABLE critical_props (
        fluid TEXT,
        property TEXT,
        value REAL,
        uncertainty REAL,
        source TEXT
    )''')

    c.execute('''CREATE TABLE saturation_ref (
        temperature_K REAL,
        pressure_bar REAL
    )''')

    for d in all_raw_data:
        c.execute('INSERT INTO nist_isotherms VALUES (?, ?, ?, ?)',
                  (d['T'], d['P'], d['V'], d['phase']))

    with open(critical_csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            c.execute('INSERT INTO critical_props VALUES (?, ?, ?, ?, ?)',
                      (row['fluid'].strip(), row['property'].strip(),
                       float(row['value']), float(row['uncertainty']),
                       row['source'].strip()))

    for s in saturation_data:
        c.execute('INSERT INTO saturation_ref VALUES (?, ?)',
                  (s['T_K'], s['P_sat_bar']))

    conn.commit()
    conn.close()


def main():
    crit = parse_critical_measurements('/app/data/critical_measurements.csv')
    init_eos_params(crit)

    saturation_data = parse_saturation_html('/app/data/co2_saturation_nist.html')

    # Collect all raw isotherm data for database
    all_raw = []
    isotherm_files = [
        ('250', 'co2_250K.tsv'), ('300', 'co2_300K.tsv'),
        ('350', 'co2_350K.tsv'), ('400', 'co2_400K.tsv')
    ]
    for _, fname in isotherm_files:
        data = parse_nist_tsv(os.path.join('/app/data', fname))
        all_raw.extend(data)

    # Create SQLite database with all parsed data
    create_database(all_raw, '/app/data/critical_measurements.csv', saturation_data)

    state_points = [(300, 10), (300, 50), (350, 100), (400, 200)]

    compressibility = compute_compressibility()
    vle = compute_vle()

    results = {
        'critical_params': {
            'Tc_K': round(TC, 4),
            'Pc_bar': round(PC, 4),
            'omega': round(OMEGA, 4)
        },
        'compressibility': compressibility,
        'fugacity': compute_fugacity(state_points),
        'departure_enthalpy': compute_departure_enthalpy(state_points),
        'second_virial': compute_second_virial(),
        'vle_prediction': vle,
        'compression_work': compute_compression_work(),
        'model_accuracy': compute_model_accuracy(compressibility, saturation_data, vle)
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json and /app/thermo.db")


if __name__ == '__main__':
    main()
