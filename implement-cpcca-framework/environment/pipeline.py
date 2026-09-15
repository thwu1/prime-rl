#!/usr/bin/env python3
"""Run cross-decomposition analysis and save results.

"""
import argparse
import sys
import numpy as np

sys.path.insert(0, '/app')
from cross_decomp import load_fields, cpcca, squared_covariance_fraction


def main():
    parser = argparse.ArgumentParser(description='Run CPCCA analysis')
    parser.add_argument('--n-modes', type=int, default=5,
                        help='Number of modes to extract')
    parser.add_argument('--alpha-x', type=float, default=1.0,
                        help='Whitening parameter for X field')
    parser.add_argument('--alpha-y', type=float, default=1.0,
                        help='Whitening parameter for Y field')
    parser.add_argument('--output', required=True,
                        help='Output path for results (.npz)')
    args = parser.parse_args()

    X, Y = load_fields()
    result = cpcca(X, Y, args.n_modes, args.alpha_x, args.alpha_y)
    scf = squared_covariance_fraction(result['singular_values'])

    np.savez(args.output,
             singular_values=result['singular_values'],
             scf=scf,
             Rx=result['Rx'], Ry=result['Ry'],
             Qx=result['Qx'], Qy=result['Qy'])
    print(f"Saved {args.n_modes}-mode decomposition to {args.output}")


if __name__ == '__main__':
    main()
