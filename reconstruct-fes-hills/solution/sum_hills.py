#!/usr/bin/env python3
"""Reconstruct free energy surfaces from PLUMED well-tempered metadynamics HILLS files.

"""

import argparse
import sys
import numpy as np


def parse_hills(filepath):
    """Parse a PLUMED HILLS file.

    Returns dict with keys: n_cv, multivariate, centers, heights, biasf,
    and either 'sigmas' (diagonal) or 'cov_matrices' (multivariate).
    """
    multivariate = False
    fields = []
    rows = []

    with open(filepath) as fh:
        for line in fh:
            stripped = line.strip()
            if stripped.startswith('#! FIELDS'):
                fields = stripped.split()[2:]
            elif stripped.startswith('#! SET multivariate'):
                multivariate = stripped.split()[-1].lower() == 'true'
            elif not stripped or stripped.startswith('#'):
                continue
            else:
                rows.append([float(x) for x in stripped.split()])

    data = np.array(rows)
    n_sigma = sum(1 for f in fields if f.startswith('sigma'))
    n_cv = len(fields) - 3 - n_sigma  # fields minus time, height, biasf

    result = {
        'n_cv': n_cv,
        'multivariate': multivariate,
        'centers': data[:, 1:1 + n_cv],
        'heights': data[:, -2],
        'biasf': data[:, -1],
    }

    if multivariate:
        sigma_raw = data[:, 1 + n_cv:1 + n_cv + n_sigma]
        n_hills = len(data)
        cov_matrices = np.zeros((n_hills, n_cv, n_cv))
        for k in range(n_hills):
            idx = 0
            for i in range(n_cv):
                for j in range(i, n_cv):
                    cov_matrices[k, i, j] = sigma_raw[k, idx]
                    cov_matrices[k, j, i] = sigma_raw[k, idx]
                    idx += 1
        result['cov_matrices'] = cov_matrices
    else:
        result['sigmas'] = data[:, 1 + n_cv:1 + n_cv + n_sigma]

    return result


def build_grid(gmin, gmax, gbins, n_cv):
    """Build uniformly-spaced bin-center grid points.

    Returns (grid_points [N, n_cv], per-dim grid arrays).
    """
    grids = []
    for i in range(n_cv):
        dx = (gmax[i] - gmin[i]) / gbins[i]
        grids.append(np.linspace(gmin[i] + dx / 2, gmax[i] - dx / 2, gbins[i]))

    if n_cv == 1:
        pts = grids[0].reshape(-1, 1)
    else:
        mesh = np.meshgrid(*grids, indexing='ij')
        pts = np.stack([m.ravel() for m in mesh], axis=1)

    return pts, grids


def compute_fes(hills, pts, gmin, gmax, periodic):
    """Sum Gaussian hills on grid and apply well-tempered correction.

    Returns (fes [N], derivs [N, n_cv]).
    """
    n_cv = hills['n_cv']
    n_pts = pts.shape[0]
    periods = np.array([(gmax[i] - gmin[i]) if periodic[i] else 0.0
                        for i in range(n_cv)])

    bias = np.zeros(n_pts)
    deriv = np.zeros((n_pts, n_cv))

    centers = hills['centers']
    heights = hills['heights']
    mv = hills['multivariate']

    for k in range(len(heights)):
        dp = pts - centers[k]

        # Apply minimum-image convention for periodic CVs
        for i in range(n_cv):
            if periodic[i]:
                dp[:, i] -= periods[i] * np.round(dp[:, i] / periods[i])

        if mv:
            cov_inv = np.linalg.inv(hills['cov_matrices'][k])
            # Quadratic form: sum_ij dp_i * cov_inv_ij * dp_j
            dp_transformed = dp @ cov_inv
            quad = np.sum(dp_transformed * dp, axis=1)
            g = heights[k] * np.exp(-0.5 * quad)
            deriv += -g[:, None] * dp_transformed
        else:
            sig = hills['sigmas'][k]
            exponent = np.sum(dp ** 2 / (2.0 * sig ** 2), axis=1)
            g = heights[k] * np.exp(-exponent)
            deriv += -g[:, None] * dp / (sig ** 2)

        bias += g

    # Well-tempered correction: F(s) = -gamma/(gamma-1) * V(s)
    gamma = hills['biasf'][0]
    if gamma > 1.0:
        factor = -gamma / (gamma - 1.0)
    else:
        factor = -1.0

    return factor * bias, factor * deriv


def write_output(filepath, pts, fes, derivs, grids, n_cv):
    """Write FES grid to output file."""
    with open(filepath, 'w') as fh:
        if n_cv == 1:
            for i in range(len(pts)):
                fh.write(f"{pts[i, 0]:.10f} {fes[i]:.10f} {derivs[i, 0]:.10f}\n")
        elif n_cv == 2:
            n1 = len(grids[0])
            n2 = len(grids[1])
            for i in range(n1):
                for j in range(n2):
                    idx = i * n2 + j
                    fh.write(
                        f"{pts[idx, 0]:.10f} {pts[idx, 1]:.10f} "
                        f"{fes[idx]:.10f} {derivs[idx, 0]:.10f} {derivs[idx, 1]:.10f}\n"
                    )
                fh.write("\n")


def main():
    parser = argparse.ArgumentParser(
        description='Reconstruct FES from PLUMED HILLS file'
    )
    parser.add_argument('--hills', required=True, help='HILLS file path')
    parser.add_argument('--grid-min', required=True,
                        help='Grid minimums (comma-separated)')
    parser.add_argument('--grid-max', required=True,
                        help='Grid maximums (comma-separated)')
    parser.add_argument('--grid-bins', required=True,
                        help='Number of bins (comma-separated)')
    parser.add_argument('--periodic', required=True,
                        help='Periodicity per dim (comma-separated true/false)')
    parser.add_argument('--outfile', required=True, help='Output file path')

    args = parser.parse_args()

    gmin = [float(x) for x in args.grid_min.split(',')]
    gmax = [float(x) for x in args.grid_max.split(',')]
    gbins = [int(x) for x in args.grid_bins.split(',')]
    periodic = [x.strip().lower() == 'true' for x in args.periodic.split(',')]

    hills = parse_hills(args.hills)

    if hills['n_cv'] != len(gmin):
        print(f"Error: HILLS has {hills['n_cv']} CVs but grid spec has {len(gmin)}",
              file=sys.stderr)
        sys.exit(1)

    pts, grids = build_grid(gmin, gmax, gbins, hills['n_cv'])
    fes, derivs = compute_fes(hills, pts, gmin, gmax, periodic)
    write_output(args.outfile, pts, fes, derivs, grids, hills['n_cv'])


if __name__ == '__main__':
    main()
