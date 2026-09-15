#!/usr/bin/env python3
"""
Generate 2D anisotropic diffusion matrices in Matrix Market format.

Discretizes  -d/dx(du/dx) - epsilon * d/dy(du/dy) = f  on [0,1]^2
with homogeneous Dirichlet boundary conditions using a standard
5-point finite difference stencil on an n x n interior grid.

Stencil (scaled by h^2):
    center:     2(1 + epsilon)
    x-neighbors: -1
    y-neighbors: -epsilon

The resulting matrix is symmetric positive definite of size n^2 x n^2.
Node ordering: row-major, index = j*n + i where i is x-index, j is y-index.

Usage:
    python3 generate_matrix.py                        # generate default test matrices
    python3 generate_matrix.py --n 48 --epsilon 0.01 --output /app/data/custom.mtx
"""

import argparse
import os
import sys


def generate_aniso_diffusion_mtx(n, epsilon, filepath):
    """Write 2D anisotropic diffusion matrix to Matrix Market file."""
    N = n * n
    entries = []

    for j in range(n):
        for i in range(n):
            idx = j * n + i

            # y-direction: bottom neighbor (j-1)
            if j > 0:
                entries.append((idx, idx - n, -epsilon))

            # x-direction: left neighbor (i-1)
            if i > 0:
                entries.append((idx, idx - 1, -1.0))

            # diagonal
            entries.append((idx, idx, 2.0 * (1.0 + epsilon)))

            # x-direction: right neighbor (i+1)
            if i < n - 1:
                entries.append((idx, idx + 1, -1.0))

            # y-direction: top neighbor (j+1)
            if j < n - 1:
                entries.append((idx, idx + n, -epsilon))

    nnz = len(entries)

    with open(filepath, 'w') as f:
        f.write("%%MatrixMarket matrix coordinate real general\n")
        f.write("%% 2D anisotropic diffusion: n={}, epsilon={}\n".format(n, epsilon))
        f.write("{} {} {}\n".format(N, N, nnz))
        for row, col, val in entries:
            f.write("{} {} {:.15e}\n".format(row + 1, col + 1, val))


def main():
    parser = argparse.ArgumentParser(description="Generate anisotropic diffusion matrix")
    parser.add_argument('--n', type=int, default=0, help='Grid points per dimension')
    parser.add_argument('--epsilon', type=float, default=1.0, help='Anisotropy ratio')
    parser.add_argument('--output', type=str, default='', help='Output .mtx file path')
    args = parser.parse_args()

    if args.n > 0 and args.output:
        os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
        generate_aniso_diffusion_mtx(args.n, args.epsilon, args.output)
        print("Generated {}x{} matrix (epsilon={}) -> {}".format(
            args.n * args.n, args.n * args.n, args.epsilon, args.output))
    else:
        # Default: generate standard test matrices
        os.makedirs('/app/data', exist_ok=True)
        for n, eps, name in [
            (32, 1.0,   'iso_32.mtx'),
            (64, 1.0,   'iso_64.mtx'),
            (32, 0.001, 'aniso_32.mtx'),
        ]:
            path = '/app/data/' + name
            generate_aniso_diffusion_mtx(n, eps, path)
            print("Generated {}: {}x{}, epsilon={}".format(name, n*n, n*n, eps))


if __name__ == '__main__':
    main()
