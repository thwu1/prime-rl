"""Generate target fields for the two-phase diffusion inverse problem."""
import numpy as np

N = 64
h = 1.0 / N
h_inv_sq = 1.0 / (h * h)

kappa_1 = 0.01
kappa_2 = 0.0042
dt = 0.005
n_steps_1 = 10
n_steps_2 = 8

x = np.linspace(0, 1, N, endpoint=False)
y = np.linspace(0, 1, N, endpoint=False)
X, Y = np.meshgrid(x, y)

# IC for experiment A (unknown to solver — must be recovered)
ic_a = (np.sin(2.0 * np.pi * X) * np.sin(2.0 * np.pi * Y) +
        0.5 * np.cos(4.0 * np.pi * X) * np.sin(2.0 * np.pi * Y))

# IC for experiment B (known to solver — used for kappa_2 calibration)
ic_b = (0.8 * np.cos(2.0 * np.pi * X) * np.sin(4.0 * np.pi * Y) +
        0.4 * np.sin(2.0 * np.pi * X) * np.cos(2.0 * np.pi * Y))


def evolve(u, kappa, n_steps):
    u = u.copy()
    for _ in range(n_steps):
        lap = (np.roll(u, -1, axis=0) + np.roll(u, 1, axis=0) +
               np.roll(u, -1, axis=1) + np.roll(u, 1, axis=1) - 4.0 * u) * h_inv_sq
        u = u + kappa * dt * lap
    return u


# Two-phase evolution: phase 1 (kappa_1) then phase 2 (kappa_2)
target_a = evolve(evolve(ic_a, kappa_1, n_steps_1), kappa_2, n_steps_2)
target_b = evolve(evolve(ic_b, kappa_1, n_steps_1), kappa_2, n_steps_2)

np.save("/app/target_a.npy", target_a)
np.save("/app/target_b.npy", target_b)
np.save("/app/known_ic_b.npy", ic_b)
