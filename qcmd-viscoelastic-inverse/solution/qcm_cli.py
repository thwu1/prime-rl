#!/usr/bin/env python3
"""
CLI tool for QCM-D analysis.

Usage:
    python3 qcm_cli.py --input input.json --output output.json
"""


import argparse
import json
import sys

from qcm_analysis import calc_delfstar, solve_inverse


def parse_layers(layers_raw):
    """Convert JSON layers (string keys, possibly large drho) to internal format."""
    layers = {}
    for key, props in layers_raw.items():
        layer_num = int(key)
        drho = props['drho']
        if isinstance(drho, str) and drho.lower() == 'inf':
            drho = float('inf')
        elif drho > 1e100:
            drho = float('inf')
        layers[layer_num] = {
            'grho3': float(props['grho3']),
            'phi': float(props['phi']),
            'drho': drho,
        }
    return layers


def run_forward(data):
    """Run forward calculation."""
    harmonics = data['harmonics']
    layers = parse_layers(data['layers'])

    result = {}
    for n in harmonics:
        dfs = calc_delfstar(n, layers)
        result[str(n)] = [dfs.real, dfs.imag]

    return {'delfstar': result}


def run_inverse(data):
    """Run inverse calculation."""
    layers = parse_layers(data['layers'])

    delfstar_expt = {}
    for key, val in data['delfstar_expt'].items():
        n = int(key)
        delfstar_expt[n] = complex(val[0], val[1])

    harmonics_f = [int(h) for h in data['harmonics_f']]
    harmonics_g = [int(h) for h in data['harmonics_g']]

    solution = solve_inverse(delfstar_expt, harmonics_f, harmonics_g, layers)

    layers_recovered = dict(layers)
    layers_recovered[1] = {
        'grho3': solution['grho3'],
        'phi': solution['phi'],
        'drho': solution['drho'],
    }

    max_residual = 0.0
    for n in harmonics_f:
        calc = calc_delfstar(n, layers_recovered)
        max_residual = max(max_residual,
                           abs(calc.real - delfstar_expt[n].real))
    for n in harmonics_g:
        calc = calc_delfstar(n, layers_recovered)
        max_residual = max(max_residual,
                           abs(calc.imag - delfstar_expt[n].imag))

    return {
        'solution': solution,
        'residual_hz': max_residual,
    }


def main():
    parser = argparse.ArgumentParser(description='QCM-D Analysis CLI')
    parser.add_argument('--input', required=True, help='Input JSON file path')
    parser.add_argument('--output', required=True,
                        help='Output JSON file path')
    args = parser.parse_args()

    with open(args.input) as f:
        data = json.load(f)

    mode = data['mode']
    if mode == 'forward':
        result = run_forward(data)
    elif mode == 'inverse':
        result = run_inverse(data)
    else:
        print(f"Unknown mode: {mode}", file=sys.stderr)
        sys.exit(1)

    with open(args.output, 'w') as f:
        json.dump(result, f, indent=2)


if __name__ == '__main__':
    main()
