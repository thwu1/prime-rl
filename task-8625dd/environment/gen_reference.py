"""Generate reference validation data from analytical solutions."""
import numpy as np
import os

os.makedirs('/app/reference', exist_ok=True)

N = 64
Re_known = 100.0
nu = 1.0 / Re_known
dt = 0.01
T = 5.0

x = np.linspace(0, 2 * np.pi, N, endpoint=False)
X, Y = np.meshgrid(x, x, indexing='ij')

omega_T5 = 2.0 * np.cos(X) * np.cos(Y) * np.exp(-2 * nu * T)

nsteps = int(T / dt)
times = np.arange(nsteps + 1) * dt
energies = 0.25 * np.exp(-4 * nu * times)
enstrophies = 0.5 * np.exp(-4 * nu * times)

np.savez('/app/reference/taylor_green_N64.npz',
         omega_T5=omega_T5, times=times,
         energies=energies, enstrophies=enstrophies,
         X=X, Y=Y)

Re_unknown = 237.5
nu_unknown = 1.0 / Re_unknown
T_unknown = 20.0
dt_unknown = 0.1
n_unknown = int(T_unknown / dt_unknown)
t_unknown = np.arange(n_unknown + 1) * dt_unknown
e_unknown = 0.25 * np.exp(-4 * nu_unknown * t_unknown)
rng = np.random.RandomState(42)
e_unknown += rng.normal(0, 1e-10, len(e_unknown))

with open('/app/reference/unknown_decay.csv', 'w') as f:
    f.write('time,energy\n')
    for t, e in zip(t_unknown, e_unknown):
        f.write(f'{t:.6f},{e:.15e}\n')

print("Reference data generated successfully.")
