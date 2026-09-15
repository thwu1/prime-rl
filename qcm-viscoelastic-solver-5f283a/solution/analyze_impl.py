#!/usr/bin/env python3
"""
QCM-D data analysis pipeline.

Reads crystal configuration and experimental data, runs appropriate
analysis (calibration, Sauerbrey, or Voigt inverse fitting), and
writes structured results.
"""


import json
import csv
import sys
import os

try:
    import tomllib
except ImportError:
    import tomli as tomllib

sys.path.insert(0, '/app')
import qcm_engine


def read_config(path='/app/config/crystal.toml'):
    with open(path, 'rb') as f:
        return tomllib.load(f)


def read_experiment(exp_dir):
    with open(os.path.join(exp_dir, 'metadata.json')) as f:
        metadata = json.load(f)
    rows = []
    with open(os.path.join(exp_dir, 'measurements.csv')) as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return metadata, rows


def convert_measurements(raw_rows, f1):
    """Convert CSV rows with delta_D_1e6 to {n: {delf, delg}} dict."""
    measurements = {}
    for row in raw_rows:
        n = int(row['harmonic'])
        delf = float(row['delf_hz'])
        delta_D = float(row['delta_D_1e6'])
        # ΔΓ = ΔD × n × f1 / 2
        delg = delta_D * 1e-6 * n * f1 / 2.0
        measurements[n] = {'delf': delf, 'delg': delg}
    return measurements


def analyze_calibration(measurements, metadata, f1, Zq):
    known_grho3 = metadata['known_medium']['grho3']
    harmonics = sorted(measurements.keys())
    layers_init = {1: {'grho3': 1e8, 'phi': 90.0, 'drho': float('inf')}}

    solved = qcm_engine.inverse_calc(
        measurements, harmonics, harmonics,
        ['grho3_1'], layers_init,
        f1=f1, Zq=Zq,
        bounds={'grho3_1': (1e5, 1e10)},
    )
    fitted = solved['grho3_1']
    return {
        'fitted_grho3': fitted,
        'known_grho3': known_grho3,
        'relative_error': abs(fitted - known_grho3) / known_grho3,
    }


def analyze_rigid_film(measurements, f1, Zq):
    drho_vals = {}
    for n, meas in measurements.items():
        drho_vals[str(n)] = -meas['delf'] * Zq / (2.0 * n * f1 ** 2)
    avg = sum(drho_vals.values()) / len(drho_vals)
    return {
        'sauerbrey_drho': avg,
        'drho_per_harmonic': drho_vals,
    }


def analyze_viscoelastic(measurements, metadata, f1, Zq):
    bulk = metadata['bulk_liquid']
    harmonics = sorted(measurements.keys())
    layers_init = {
        1: {'grho3': 1e9, 'phi': 45.0, 'drho': 2e-4},
        2: {'grho3': bulk['grho3'], 'phi': bulk['phi'], 'drho': float('inf')},
    }
    solved = qcm_engine.inverse_calc(
        measurements, harmonics, harmonics,
        ['grho3_1', 'phi_1', 'drho_1'],
        layers_init,
        f1=f1, Zq=Zq,
        bounds={
            'grho3_1': (1e6, 1e12),
            'phi_1': (0.0, 89.0),
            'drho_1': (1e-6, 1e-2),
        },
    )
    return {
        'grho3': solved['grho3_1'],
        'phi': solved['phi_1'],
        'drho': solved['drho_1'],
    }


def main():
    config = read_config()
    f1 = config['crystal']['f1_hz']
    Zq = config['crystal']['Zq_kgm2s']

    results = {}
    data_dir = '/app/data'
    for exp_name in sorted(os.listdir(data_dir)):
        exp_dir = os.path.join(data_dir, exp_name)
        if not os.path.isdir(exp_dir):
            continue
        metadata, raw_rows = read_experiment(exp_dir)
        measurements = convert_measurements(raw_rows, f1)
        exp_type = metadata['type']

        if exp_type == 'calibration':
            results[exp_name] = analyze_calibration(measurements, metadata, f1, Zq)
        elif exp_type == 'rigid_film':
            results[exp_name] = analyze_rigid_film(measurements, f1, Zq)
        elif exp_type == 'viscoelastic_in_liquid':
            results[exp_name] = analyze_viscoelastic(measurements, metadata, f1, Zq)

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)
    print('Results written to /app/results.json')


if __name__ == '__main__':
    main()
