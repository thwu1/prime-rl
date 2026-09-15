#!/usr/bin/env python3
"""Generate the task matrix: a Gaussian kernel matrix from clustered point cloud data."""
import numpy as np
import os

def generate():
    rng = np.random.RandomState(54321)
    m, n = 3000, 1200
    dim = 3

    # Source points in 3D with cluster structure
    sources = np.vstack([
        rng.randn(600, dim) * 0.5 + np.array([5, 0, 0]),
        rng.randn(600, dim) * 0.3 + np.array([-5, 0, 0]),
        rng.randn(600, dim) * 1.0 + np.array([0, 5, 0]),
        rng.randn(600, dim) * 0.2 + np.array([0, -5, 0]),
        rng.randn(600, dim) * 2.0
    ])

    # Target points in 3D
    targets = np.vstack([
        rng.randn(300, dim) * 0.5 + np.array([5, 0, 0]),
        rng.randn(300, dim) * 0.5 + np.array([0, 0, 5]),
        rng.randn(300, dim) * 0.5 + np.array([0, 0, -5]),
        rng.randn(300, dim) * 1.5
    ])

    bandwidth = 3.0

    # Compute squared distance matrix efficiently (column-wise to limit memory)
    sq_dist = np.zeros((m, n), dtype=np.float64)
    for d in range(dim):
        diff = sources[:, d:d+1] - targets[:, d:d+1].T
        sq_dist += diff ** 2

    A = np.exp(-sq_dist / (2 * bandwidth ** 2))

    os.makedirs('/app/data', exist_ok=True)
    np.save('/app/data/matrix.npy', A)

    with open('/app/data/README.txt', 'w') as f:
        f.write("Matrix shape: {} x {}\n".format(A.shape[0], A.shape[1]))
        f.write("Matrix dtype: {}\n".format(A.dtype))
        f.write("This matrix is derived from a computational kernel evaluation.\n")
        f.write("Analyze its spectral properties, leverage scores, and low-rank approximations.\n")

    print("Generated matrix: shape={}, dtype={}".format(A.shape, A.dtype))

if __name__ == '__main__':
    generate()
