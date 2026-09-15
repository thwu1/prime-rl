#!/usr/bin/env python3
"""Generate observation data in HDF5 format.

Runs during Docker build only. Produces observations but NO reference
posteriors -- those are generated at test time to prevent cheating.
"""
import numpy as np
import h5py


def _simulate_py(theta, rng):
    """Two Moons forward model (Python, used only for observation generation)."""
    n = theta.shape[0]
    a = rng.uniform(-np.pi / 2, np.pi / 2, size=(n, 1))
    r = rng.normal(0.1, 0.01, size=(n, 1))
    p = np.hstack([np.cos(a) * r + 0.25, np.sin(a) * r])
    ang = -np.pi / 4.0
    c, s = np.cos(ang), np.sin(ang)
    z0 = (c * theta[:, 0] - s * theta[:, 1]).reshape(-1, 1)
    z1 = (s * theta[:, 0] + c * theta[:, 1]).reshape(-1, 1)
    return p + np.hstack([-np.abs(z0), z1])


def main():
    param_seeds = [42, 137, 256]
    obs_seeds = [1000011, 1000001, 1000002]

    with h5py.File('/app/observations.h5', 'w') as f:
        for i in range(3):
            rng_p = np.random.RandomState(param_seeds[i])
            theta_true = rng_p.uniform(-1, 1, size=(1, 2))

            rng_o = np.random.RandomState(obs_seeds[i])
            obs = _simulate_py(theta_true, rng_o)

            f.create_dataset(f'obs_{i + 1}', data=obs)

        f.attrs['dim_parameters'] = 2
        f.attrs['dim_data'] = 2
        f.attrs['prior_low'] = -1.0
        f.attrs['prior_high'] = 1.0
        f.attrs['num_observations'] = 3
        f.attrs['num_posterior_samples'] = 10000

    print("Observations written to /app/observations.h5")


if __name__ == '__main__':
    main()
