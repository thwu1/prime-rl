#!/usr/bin/env python3
"""Generate SPHinXsys-format XML regression test data for dambreak benchmark.

Creates multi-resolution ensemble data with a planted anomalous run,
2nd-order spatial convergence structure, and realistic SPH time series.
"""

import math
import os
import json


def sigmoid(x, k=5.0, x0=0.0):
    """Logistic sigmoid function with overflow protection."""
    arg = -k * (x - x0)
    arg = max(-700.0, min(700.0, arg))
    return 1.0 / (1.0 + math.exp(arg))


def pressure_exact(t):
    """Exact pressure at observer for 2D dambreak: rise, peak, oscillate, settle."""
    rise = sigmoid(t, k=5.0, x0=1.5)
    osc = 0.1 * math.sin(4.0 * t) * math.exp(-0.5 * t)
    return rise + osc


def energy_exact(t):
    """Exact total mechanical energy: exponential decay due to viscous dissipation."""
    return math.exp(-0.1 * t)


def pressure_with_resolution(t, h, run_offset=0.0):
    """Pressure with 2nd-order resolution-dependent error."""
    base = pressure_exact(t)
    h_ratio_sq = (h / 0.0125) ** 2
    resolution_error = h_ratio_sq * 0.001 * math.sin(2.0 * math.pi * t / 5.0)
    return base + resolution_error + run_offset


def energy_with_resolution(t, h, run_offset=0.0):
    """Energy with 2nd-order numerical dissipation error."""
    base = energy_exact(t)
    h_ratio_sq = (h / 0.0125) ** 2
    resolution_error = h_ratio_sq * 0.0005 * t
    return base - resolution_error + run_offset


def create_xml(values, n_snapshots):
    """Create SPHinXsys XML regression data in authentic attribute format."""
    lines = ['<?xml version="1.0" encoding="UTF-8" ?>']
    lines.append('<result>')
    lines.append('    <Snapshot_Element>')
    attr = 'number_of_snapshot_for_local_result_="{}"'.format(n_snapshots)
    lines.append('        <Snapshot {} />'.format(attr))
    lines.append('    </Snapshot_Element>')
    lines.append('    <Result_Element>')

    attrs = []
    for i, v in enumerate(values):
        attrs.append('snapshot_{}="{:.15e}"'.format(i, v))
    lines.append('        <Particle_0 {} />'.format(' '.join(attrs)))

    lines.append('    </Result_Element>')
    lines.append('</result>')
    return '\n'.join(lines)


def main():
    n_snapshots = 20
    times = [i * 0.25 for i in range(n_snapshots)]

    resolutions = {
        'fine': 0.0125,
        'medium': 0.025,
        'coarse': 0.05,
    }

    quantity_funcs = {
        'Pressure': pressure_with_resolution,
        'TotalMechanicalEnergy': energy_with_resolution,
    }

    # 5 normal runs with symmetric offsets (mean offset = 0)
    normal_offsets = [0.0, 0.0001, 0.0002, -0.0001, -0.0002]
    anomalous_offset = 0.05

    base_dir = '/app/data'

    for res_name, h in resolutions.items():
        for qty_name, qty_func in quantity_funcs.items():
            qty_dir = os.path.join(base_dir, res_name, qty_name)
            os.makedirs(qty_dir, exist_ok=True)

            # Reference data (zero offset for this resolution)
            ref_values = [qty_func(t, h, 0.0) for t in times]
            with open(os.path.join(qty_dir, 'reference.xml'), 'w') as f:
                f.write(create_xml(ref_values, n_snapshots))

            # Normal ensemble runs
            for run_idx, offset in enumerate(normal_offsets):
                values = [qty_func(t, h, offset) for t in times]
                fname = 'run_{}.xml'.format(run_idx)
                with open(os.path.join(qty_dir, fname), 'w') as f:
                    f.write(create_xml(values, n_snapshots))

            # Anomalous run for medium resolution only
            if res_name == 'medium':
                values = [qty_func(t, h, anomalous_offset) for t in times]
                with open(os.path.join(qty_dir, 'run_5.xml'), 'w') as f:
                    f.write(create_xml(values, n_snapshots))

    # Write analysis configuration
    config = {
        'resolutions': {
            name: {'h': h, 'label': name}
            for name, h in resolutions.items()
        },
        'quantities': list(quantity_funcs.keys()),
        'n_snapshots': n_snapshots,
        'times': times,
        'band_fraction': 0.1,
        'distance_threshold': 0.05,
        'convergence_threshold_mean': 0.001,
        'convergence_threshold_variance': 0.1,
        'outlier_score_threshold': 3.5,
        'refinement_ratio': 2.0
    }
    with open(os.path.join(base_dir, 'config.json'), 'w') as f:
        json.dump(config, f, indent=2)

    print('Data generation complete: {} resolutions x {} quantities'.format(
        len(resolutions), len(quantity_funcs)))


if __name__ == '__main__':
    main()
