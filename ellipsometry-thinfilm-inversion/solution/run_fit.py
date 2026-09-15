
"""
Spectroscopic ellipsometry inversion: fit thin-film parameters
(thickness, Cauchy A, Cauchy B) from measured psi/Delta data.
"""

import csv
import json
import numpy as np
from numpy import inf, pi
from scipy.interpolate import interp1d
from scipy.optimize import least_squares

from tmm_solver import ellips


def load_si_nk(filepath):
    """Load Si optical constants and return interpolation functions."""
    wl, n_vals, k_vals = [], [], []
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            wl.append(float(row['wavelength_nm']))
            n_vals.append(float(row['n']))
            k_vals.append(float(row['k']))
    n_fn = interp1d(wl, n_vals, kind='cubic')
    k_fn = interp1d(wl, k_vals, kind='cubic')
    return n_fn, k_fn


def load_measurements(filepath):
    """Load measurement data from CSV."""
    data = []
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            data.append({
                'wavelength_nm': float(row['wavelength_nm']),
                'angle_deg': float(row['angle_deg']),
                'psi_rad': float(row['psi_rad']),
                'Delta_rad': float(row['Delta_rad']),
            })
    return data


def load_config(filepath):
    """Load stack configuration."""
    with open(filepath) as f:
        return json.load(f)


def residuals(params, measurements, si_n_fn, si_k_fn):
    """Compute residual vector for least-squares fitting."""
    d, A, B = params
    degree = pi / 180
    res = []

    for m in measurements:
        lam = m['wavelength_nm']
        ang = m['angle_deg']

        n_si = complex(float(si_n_fn(lam)), float(si_k_fn(lam)))
        n_film = A + B / lam ** 2

        n_list = [1, n_film, n_si]
        d_list = [inf, d, inf]

        e = ellips(n_list, d_list, ang * degree, lam)

        res.append(e['psi'] - m['psi_rad'])
        res.append(e['Delta'] - m['Delta_rad'])

    return np.array(res)


def main():
    si_n_fn, si_k_fn = load_si_nk('/app/si_nk.csv')
    measurements = load_measurements('/app/measurements.csv')
    config = load_config('/app/stack_config.json')

    # Initial guess and bounds from config
    ig = config['initial_guess']
    bounds = config['bounds']

    x0 = [ig['thickness_nm'], ig['cauchy_A'], ig['cauchy_B']]
    lower = [bounds['thickness_nm'][0], bounds['cauchy_A'][0], bounds['cauchy_B'][0]]
    upper = [bounds['thickness_nm'][1], bounds['cauchy_A'][1], bounds['cauchy_B'][1]]

    result = least_squares(
        residuals, x0,
        args=(measurements, si_n_fn, si_k_fn),
        bounds=(lower, upper),
        method='trf',
        ftol=1e-14,
        xtol=1e-14,
        gtol=1e-14,
        max_nfev=10000,
    )

    output = {
        'thickness_nm': float(result.x[0]),
        'cauchy_A': float(result.x[1]),
        'cauchy_B': float(result.x[2]),
    }

    with open('/app/results.json', 'w') as f:
        json.dump(output, f, indent=2)

    print(f"Fitted parameters:")
    print(f"  thickness = {output['thickness_nm']:.4f} nm")
    print(f"  Cauchy A  = {output['cauchy_A']:.6f}")
    print(f"  Cauchy B  = {output['cauchy_B']:.2f} nm^2")
    print(f"  Cost      = {result.cost:.2e}")


if __name__ == '__main__':
    main()
