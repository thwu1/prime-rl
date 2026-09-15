#!/usr/bin/env python3
"""Generate observations and reference posterior samples for the Two Moons model."""
import math
import random
import csv
import os


def simulate_one(theta, rng):
    """Two Moons simulator (single sample)."""
    a = rng.uniform(-math.pi / 2, math.pi / 2)
    r = rng.gauss(0.1, 0.01)
    p1 = math.cos(a) * r + 0.25
    p2 = math.sin(a) * r
    ang = -math.pi / 4.0
    c = math.cos(ang)
    s = math.sin(ang)
    z0 = c * theta[0] - s * theta[1]
    z1 = s * theta[0] + c * theta[1]
    return p1 - abs(z0), p2 + z1


def sample_ref_posterior(obs, n, rng):
    """Sample from exact posterior via analytical inversion."""
    samples = []
    ang = -math.pi / 4.0
    ci = math.cos(-ang)
    si = math.sin(-ang)
    while len(samples) < n:
        a = rng.uniform(-math.pi / 2, math.pi / 2)
        r = rng.gauss(0.1, 0.01)
        p1 = math.cos(a) * r + 0.25
        p2 = math.sin(a) * r
        q0 = p1 - obs[0]
        q1 = obs[1] - p2
        if rng.random() < 0.5:
            q0 = -q0
        t0 = ci * q0 - si * q1
        t1 = si * q0 + ci * q1
        if -1.0 <= t0 <= 1.0 and -1.0 <= t1 <= 1.0:
            samples.append((t0, t1))
    return samples


def main():
    os.makedirs('/app/data', exist_ok=True)
    true_params = [(0.3, -0.2), (-0.5, 0.7), (0.8, 0.4)]
    for i, tp in enumerate(true_params, 1):
        rng_obs = random.Random(42000 + i)
        obs = simulate_one(tp, rng_obs)
        with open(f'/app/data/observation_{i}.csv', 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['x1', 'x2'])
            w.writerow([f'{obs[0]:.12f}', f'{obs[1]:.12f}'])
        rng_ref = random.Random(100000 + i)
        refs = sample_ref_posterior(obs, 10000, rng_ref)
        with open(f'/app/data/reference_posterior_{i}.csv', 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['theta1', 'theta2'])
            for s in refs:
                w.writerow([f'{s[0]:.12f}', f'{s[1]:.12f}'])
        print(f'Obs {i}: ({obs[0]:.6f}, {obs[1]:.6f}), {len(refs)} ref samples')


if __name__ == '__main__':
    main()
