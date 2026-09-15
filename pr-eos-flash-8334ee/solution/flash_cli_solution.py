#!/usr/bin/env python3
"""CLI wrapper for PR EOS mixture flash calculator.


Usage:
    python3 flash_cli.py <input.json>

Input JSON keys: T, P, zs, Tcs, Pcs, omegas, kijs
Output JSON keys: VF, xs, ys, phis_l, phis_g
"""

import json
import sys

from pr_mix import flash_pt, mixture_fugacity_coefficients


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 flash_cli.py <input.json>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        data = json.load(f)

    T = data['T']
    P = data['P']
    zs = data['zs']
    Tcs = data['Tcs']
    Pcs = data['Pcs']
    omegas = data['omegas']
    kijs = data['kijs']

    result = flash_pt(T, P, zs, Tcs, Pcs, omegas, kijs)

    xs = result['xs']
    ys = result['ys']

    phis_l = mixture_fugacity_coefficients(T, P, xs, Tcs, Pcs, omegas, kijs, 'liquid')
    phis_g = mixture_fugacity_coefficients(T, P, ys, Tcs, Pcs, omegas, kijs, 'vapor')

    output = {
        'VF': result['VF'],
        'xs': xs,
        'ys': ys,
        'phis_l': phis_l,
        'phis_g': phis_g,
    }

    print(json.dumps(output))


if __name__ == '__main__':
    main()
