
"""
CLI helper for tmm_cli.sh — handles compute and sweep subcommands.
Reads JSON from stdin, calls the TMM solver, outputs JSON or SQLite.
"""

import sys
import json
import sqlite3
import numpy as np
from numpy import inf

sys.path.insert(0, '/app')
from tmm_solver import coh_tmm


def parse_n(val):
    """Parse a refractive index from JSON (float or [real, imag])."""
    if isinstance(val, list):
        return complex(val[0], val[1])
    return complex(val)


def parse_d(val):
    """Parse a thickness from JSON (float or 'inf')."""
    if val == "inf":
        return inf
    return float(val)


def cmd_compute(data):
    """Compute TMM for a single configuration, output JSON to stdout."""
    n_list = [parse_n(n) for n in data['n_list']]
    d_list = [parse_d(d) for d in data['d_list']]
    result = coh_tmm(
        data['pol'], n_list, d_list,
        float(data['th_0']), float(data['lam_vac']))
    out = {
        'R': float(result['R']),
        'T': float(result['T']),
        'r_real': float(result['r'].real),
        'r_imag': float(result['r'].imag),
    }
    json.dump(out, sys.stdout)
    sys.stdout.write('\n')


def cmd_sweep(data):
    """Compute wavelength sweep, store results in SQLite database."""
    n_list = [parse_n(n) for n in data['n_list']]
    d_list = [parse_d(d) for d in data['d_list']]
    th_0 = float(data['th_0'])
    lam_min = float(data['lam_min'])
    lam_max = float(data['lam_max'])
    lam_count = int(data['lam_count'])

    wavelengths = np.linspace(lam_min, lam_max, lam_count)

    conn = sqlite3.connect('/app/sweep_results.db')
    conn.execute(
        'CREATE TABLE IF NOT EXISTS sweep '
        '(wavelength_nm REAL, R_s REAL, T_s REAL, R_p REAL, T_p REAL)')
    conn.execute('DELETE FROM sweep')

    for lam in wavelengths:
        lam_f = float(lam)
        s = coh_tmm('s', n_list, d_list, th_0, lam_f)
        p = coh_tmm('p', n_list, d_list, th_0, lam_f)
        conn.execute(
            'INSERT INTO sweep VALUES (?, ?, ?, ?, ?)',
            (lam_f, float(s['R']), float(s['T']),
             float(p['R']), float(p['T'])))

    conn.commit()
    conn.close()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: tmm_cli_impl.py {compute|sweep}", file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]
    data = json.load(sys.stdin)

    if cmd == 'compute':
        cmd_compute(data)
    elif cmd == 'sweep':
        cmd_sweep(data)
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)
