"""Process stacks.yaml and produce results.json and results.db using the TMM engine."""

import json
import sqlite3
import yaml
import numpy as np
from numpy import inf, pi
import tmm_engine


def parse_complex(val):
    """Parse a complex number from YAML (string or float)."""
    if isinstance(val, str):
        return complex(val.replace(' ', ''))
    return complex(val)


def parse_d(val):
    """Parse a d_list entry (handles inf)."""
    if val is None or val == float('inf'):
        return float('inf')
    return float(val)


def solve_basic(config):
    n_list = [parse_complex(n) for n in config['n_list']]
    d_list = [parse_d(d) for d in config['d_list']]
    th_0 = config['th_0']
    lam_vac = config['lam_vac']

    s_data = tmm_engine.coh_tmm('s', n_list, d_list, th_0, lam_vac)
    p_data = tmm_engine.coh_tmm('p', n_list, d_list, th_0, lam_vac)
    e_data = tmm_engine.ellips(n_list, d_list, th_0, lam_vac)

    return {
        'R_s': float(s_data['R']),
        'T_s': float(s_data['T']),
        'R_p': float(p_data['R']),
        'T_p': float(p_data['T']),
        'psi': float(e_data['psi']),
        'Delta': float(e_data['Delta']),
    }


def solve_spr(config):
    n_list = [parse_complex(n) for n in config['n_list']]
    d_list = [parse_d(d) for d in config['d_list']]
    lam_vac = config['lam_vac']

    sweep = config['sweep_th0_deg']
    deg = pi / 180
    angles = np.linspace(sweep[0] * deg, sweep[1] * deg, int(sweep[2]))

    R_values = np.empty(len(angles))
    for i, theta in enumerate(angles):
        data = tmm_engine.coh_tmm('p', n_list, d_list, theta, lam_vac)
        R_values[i] = data['R']

    min_idx = int(np.argmin(R_values))
    return {
        'spr_angle_deg': float(angles[min_idx] / deg),
        'R_min': float(R_values[min_idx]),
    }


def solve_ar_coating(config):
    n_list = [parse_complex(n) for n in config['n_list']]
    lam_vac = config['lam_vac']

    opt = config['optimize_d']
    thicknesses = np.linspace(opt['range'][0], opt['range'][1], 10001)
    R_values = np.empty(len(thicknesses))
    for i, d in enumerate(thicknesses):
        d_list = [inf, d, inf]
        R_values[i] = tmm_engine.coh_tmm('s', n_list, d_list, 0, lam_vac)['R']

    min_idx = int(np.argmin(R_values))
    optimal_d = float(thicknesses[min_idx])
    R_min = float(R_values[min_idx])

    bb = config['broadband']
    R_sum = 0.0
    for lam in range(int(bb['range'][0]), int(bb['range'][1]) + 1):
        d_list = [inf, optimal_d, inf]
        Rs = tmm_engine.coh_tmm('s', n_list, d_list, 0, lam)['R']
        Rp = tmm_engine.coh_tmm('p', n_list, d_list, 0, lam)['R']
        R_sum += (Rs + Rp) / 2.0
    avg_R = R_sum / (bb['range'][1] - bb['range'][0] + 1)

    return {
        'optimal_thickness_nm': optimal_d,
        'R_min': R_min,
        'avg_R_400_700': avg_R,
    }


def solve_solar_cell(config):
    n_list = [parse_complex(n) for n in config['n_list']]
    d_list = [parse_d(d) for d in config['d_list']]
    c_list = config['c_list']
    th_0 = config['th_0']
    lam_vac = config['lam_vac']

    result = {}
    for pol in ['s', 'p']:
        data = tmm_engine.inc_tmm(pol, n_list, d_list, c_list, th_0, lam_vac)
        result[f'R_{pol}'] = float(data['R'])
        result[f'T_{pol}'] = float(data['T'])
        absorp = tmm_engine.inc_absorp_in_each_layer(data)
        result[f'absorption_per_layer_{pol}'] = [float(a) for a in absorp]

    return result


def write_sqlite(results, db_path):
    """Write results to a SQLite database."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS stack_results (
        stack_name TEXT NOT NULL,
        key TEXT NOT NULL,
        value REAL NOT NULL,
        PRIMARY KEY (stack_name, key))''')
    c.execute('''CREATE TABLE IF NOT EXISTS absorption (
        stack_name TEXT NOT NULL,
        polarization TEXT NOT NULL,
        layer_index INTEGER NOT NULL,
        absorption REAL NOT NULL,
        PRIMARY KEY (stack_name, polarization, layer_index))''')

    for stack_name, values in results.items():
        for k, v in values.items():
            if isinstance(v, (int, float)):
                c.execute('INSERT INTO stack_results VALUES (?, ?, ?)',
                          (stack_name, k, float(v)))
            elif isinstance(v, list):
                # Extract polarization from key like 'absorption_per_layer_s'
                pol = k.rsplit('_', 1)[-1]
                for idx, a in enumerate(v):
                    c.execute('INSERT INTO absorption VALUES (?, ?, ?, ?)',
                              (stack_name, pol, idx, float(a)))

    conn.commit()
    conn.close()


if __name__ == '__main__':
    with open('/app/stacks.yaml') as f:
        stacks = yaml.safe_load(f)['stacks']

    results = {
        'basic': solve_basic(stacks['basic']),
        'spr': solve_spr(stacks['spr']),
        'ar_coating': solve_ar_coating(stacks['ar_coating']),
        'solar_cell': solve_solar_cell(stacks['solar_cell']),
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    write_sqlite(results, '/app/results.db')

    print("Results written to /app/results.json and /app/results.db")
