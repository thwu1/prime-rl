import numpy as np


def _simulate_batch(thetas, rng):
    """Vectorized Two Moons simulator using numpy.

    Args:
        thetas: np.ndarray of shape (n, 2)
        rng: np.random.RandomState

    Returns:
        np.ndarray of shape (n, 2)
    """
    n = thetas.shape[0]
    a = rng.uniform(-np.pi / 2, np.pi / 2, size=n)
    r = rng.normal(0.1, 0.01, size=n)
    p1 = np.cos(a) * r + 0.25
    p2 = np.sin(a) * r

    ang = -np.pi / 4.0
    c = np.cos(ang)
    s = np.sin(ang)
    z0 = c * thetas[:, 0] - s * thetas[:, 1]
    z1 = s * thetas[:, 0] + c * thetas[:, 1]

    x1 = p1 - np.abs(z0)
    x2 = p2 + z1
    return np.column_stack([x1, x2])


def smc_abc(observation, num_particles=10000, max_generations=20,
            alpha=0.5, min_epsilon=0.02, seed=42):
    """Sequential Monte Carlo ABC for the Two Moons model.

    Uses adaptive quantile-based epsilon scheduling and Gaussian
    perturbation kernel with twice the empirical covariance.

    Args:
        observation: array-like of shape (2,)
        num_particles: target number of particles per generation
        max_generations: maximum number of SMC generations
        alpha: quantile for adaptive epsilon (fraction to keep)
        min_epsilon: minimum distance threshold
        seed: random seed

    Returns:
        np.ndarray of shape (N, 2) with posterior samples
    """
    rng = np.random.RandomState(seed)
    obs = np.asarray(observation, dtype=np.float64)

    # Phase 1: Rejection ABC initialization from prior
    init_size = num_particles * 50
    particles = rng.uniform(-1.0, 1.0, size=(init_size, 2))
    sims = _simulate_batch(particles, rng)
    distances = np.linalg.norm(sims - obs, axis=1)

    idx = np.argsort(distances)[:num_particles]
    particles = particles[idx].copy()
    distances = distances[idx].copy()
    weights = np.ones(num_particles) / num_particles
    epsilon = float(distances[-1])

    # Phase 2: SMC refinement
    for gen in range(max_generations):
        new_epsilon = float(np.quantile(distances, alpha))
        new_epsilon = max(new_epsilon, min_epsilon)

        if new_epsilon >= epsilon * 0.99:
            new_epsilon = max(epsilon * 0.5, min_epsilon)

        epsilon = new_epsilon

        # Perturbation kernel covariance: 2x weighted empirical covariance
        cov = 2.0 * np.cov(particles.T, aweights=weights)
        cov += np.eye(2) * 1e-8

        new_particles = np.empty((0, 2))
        new_distances = np.empty(0)
        batch_size = num_particles * 10

        for _ in range(100):
            parent_idx = rng.choice(len(particles), size=batch_size, p=weights)
            parents = particles[parent_idx]
            proposals = parents + rng.multivariate_normal(
                [0.0, 0.0], cov, size=batch_size
            )

            # Prior bounds check
            in_bounds = np.all((proposals >= -1.0) & (proposals <= 1.0), axis=1)
            proposals = proposals[in_bounds]
            if len(proposals) == 0:
                continue

            sims = _simulate_batch(proposals, rng)
            dists = np.linalg.norm(sims - obs, axis=1)
            accepted = dists < epsilon

            if np.any(accepted):
                new_particles = np.vstack([new_particles, proposals[accepted]])
                new_distances = np.concatenate([new_distances, dists[accepted]])

            if len(new_particles) >= num_particles:
                break

        if len(new_particles) < num_particles // 4:
            break

        particles = new_particles[:num_particles]
        distances = new_distances[:num_particles]
        weights = np.ones(len(particles)) / len(particles)

        if epsilon <= min_epsilon:
            break

    return particles
