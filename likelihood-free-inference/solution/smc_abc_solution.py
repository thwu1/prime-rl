#!/usr/bin/env python3
"""SMC-ABC solution interfacing with compiled simulator binary and HDF5 I/O."""
import numpy as np
import h5py
import subprocess
import tempfile
import os

SIMULATOR = '/app/simulator'


def simulate_batch(theta, seed=None):
    """Call compiled simulator binary for batch forward simulation.

    Writes parameters as raw binary float64, invokes the binary,
    and parses the binary output.
    """
    n = theta.shape[0]
    with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as fin:
        theta.astype(np.float64).tofile(fin)
        input_path = fin.name

    with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as fout:
        output_path = fout.name

    try:
        cmd = [SIMULATOR, '--input', input_path, '--output', output_path,
               '--n', str(n)]
        if seed is not None:
            cmd += ['--seed', str(int(seed))]
        subprocess.run(cmd, check=True, capture_output=True)
        result = np.fromfile(output_path, dtype=np.float64).reshape(n, 2)
    finally:
        os.unlink(input_path)
        os.unlink(output_path)

    return result


def smc_abc(observation, num_particles=10000, num_populations=15,
            quantile_shrink=0.5, prior_low=-1.0, prior_high=1.0,
            base_seed=42):
    """Sequential Monte Carlo Approximate Bayesian Computation.

    Uses the compiled simulator binary for all forward simulations.
    Implements adaptive epsilon schedule, Gaussian perturbation kernel,
    and multinomial resampling.
    """
    np.random.seed(base_seed)
    obs = observation.reshape(1, -1)
    dim = 2

    # --- Population 0: rejection from prior with large batch ---
    init_batch = 500000
    thetas = np.random.uniform(prior_low, prior_high, size=(init_batch, dim))
    sims = simulate_batch(thetas, seed=base_seed * 7 + 1)
    dists = np.sqrt(np.sum((sims - obs) ** 2, axis=1))

    sorted_idx = np.argsort(dists)
    particles = thetas[sorted_idx[:num_particles]].copy()
    particle_dists = dists[sorted_idx[:num_particles]].copy()
    weights = np.ones(num_particles) / num_particles

    print(f"  Pop 0: eps_max={particle_dists.max():.5f}, "
          f"eps_med={np.median(particle_dists):.5f}")

    # --- Sequential populations ---
    for t in range(1, num_populations):
        epsilon = float(np.quantile(particle_dists, quantile_shrink))
        if epsilon < 1e-8:
            print(f"  Pop {t}: converged")
            break

        print(f"  Pop {t}: eps={epsilon:.5f}")

        # Perturbation kernel covariance
        w_mean = np.average(particles, weights=weights, axis=0)
        diff = particles - w_mean
        cov = 2.0 * np.dot((diff * weights[:, None]).T, diff)
        cov += np.eye(dim) * 1e-8

        # Multinomial resampling
        indices = np.random.choice(
            num_particles, size=num_particles, p=weights)
        particles = particles[indices].copy()
        particle_dists = particle_dists[indices].copy()
        weights = np.ones(num_particles) / num_particles

        # Batch perturbation with iterative refinement
        new_particles = particles.copy()
        new_dists = particle_dists.copy()
        pending = np.arange(num_particles)

        for attempt in range(500):
            if len(pending) == 0:
                break

            n_pending = len(pending)
            perturbations = np.random.multivariate_normal(
                np.zeros(dim), cov, size=n_pending)
            proposals = particles[pending] + perturbations

            in_bounds = np.all(
                (proposals >= prior_low) & (proposals <= prior_high), axis=1)
            valid_local = np.where(in_bounds)[0]

            if len(valid_local) > 0:
                valid_proposals = proposals[valid_local]
                sim_seed = base_seed * 10000 + t * 1000 + attempt
                sims = simulate_batch(valid_proposals, seed=sim_seed)
                d = np.sqrt(np.sum((sims - obs) ** 2, axis=1))
                accepted_mask = d < epsilon
                accepted_local = valid_local[accepted_mask]

                if len(accepted_local) > 0:
                    global_idx = pending[accepted_local]
                    new_particles[global_idx] = proposals[accepted_local]
                    new_dists[global_idx] = d[accepted_mask]

                    keep_mask = np.ones(n_pending, dtype=bool)
                    keep_mask[accepted_local] = False
                    pending = pending[keep_mask]

        stuck = len(pending)
        if stuck > 0:
            print(f"    {stuck}/{num_particles} particles stuck")

        particles = new_particles
        particle_dists = new_dists
        weights = np.ones(num_particles) / num_particles

    print(f"  Final: dist_max={particle_dists.max():.5f}, "
          f"dist_med={np.median(particle_dists):.5f}")

    return particles


def main():
    # Read task configuration from HDF5 attributes
    with h5py.File('/app/observations.h5', 'r') as f:
        num_obs = int(f.attrs['num_observations'])
        num_samples = int(f.attrs['num_posterior_samples'])
        prior_low = float(f.attrs['prior_low'])
        prior_high = float(f.attrs['prior_high'])

    os.makedirs('/app/results', exist_ok=True)

    results = {}
    for obs_idx in range(1, num_obs + 1):
        print(f"\n=== Observation {obs_idx} ===")

        with h5py.File('/app/observations.h5', 'r') as f:
            obs = np.array(f[f'obs_{obs_idx}'])

        posterior = smc_abc(
            obs,
            num_particles=num_samples,
            num_populations=15,
            quantile_shrink=0.5,
            base_seed=42 + obs_idx,
        )
        posterior = np.clip(posterior, prior_low, prior_high)
        results[f'posterior_{obs_idx}'] = posterior
        print(f"  Saved {posterior.shape[0]} samples")

    # Write results as HDF5
    with h5py.File('/app/results/posteriors.h5', 'w') as f:
        for key, data in results.items():
            f.create_dataset(key, data=data)

    print("\nResults written to /app/results/posteriors.h5")


if __name__ == '__main__':
    main()
