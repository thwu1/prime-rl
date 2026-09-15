#!/usr/bin/env python3
"""
Generate the corrected PIC framework implementation.

Fixes applied:
1. Poisson solver: the spectral denominator must use k^2 (from the Laplacian
   in Fourier space), not |k|. The original code used np.abs(k) which gives
   correct results only for |k|=1 and wrong scaling for all other modes.

2. Two-stream initialization: the second beam must have velocity -v0 to create
   counter-streaming beams. The original code set both beams to +v0, which
   produces a single drifting beam with no instability.

Methods implemented:
3. deposit_charge: Cloud-in-Cell (CIC) charge deposition with linear weighting
   to two nearest grid points, using np.add.at for vectorized accumulation.

4. compute_electric_field: central finite-difference E = -dphi/dx using np.roll
   for periodic boundary handling.

5. interpolate_field_to_particles: CIC interpolation from grid to particles using
   the same linear weights as deposition (required for momentum conservation).
"""

corrected_code = '''"""
1D Electrostatic Particle-in-Cell (PIC) Simulation Framework

Uses normalized units: epsilon_0 = 1, |q_e| = 1, m_e = 1
With background density n0 = 1, plasma frequency omega_p = 1.
Particle weight: wp = n0 * L / N_particles
"""

import numpy as np
from numpy.fft import fft, ifft, fftfreq


class PICSimulation:
    def __init__(self, L, N_grid, N_particles, dt, v0=0.0,
                 perturbation_amp=0.0, perturbation_mode=1):
        self.L = L
        self.Ng = N_grid
        self.Np = N_particles
        self.dt = dt
        self.dx = L / N_grid
        self.v0 = v0
        self.perturbation_amp = perturbation_amp
        self.perturbation_mode = perturbation_mode

        self.x_grid = np.linspace(0, L, N_grid, endpoint=False)
        self.x = None
        self.v = None

        self.qm = -1.0
        self.n0 = 1.0
        self.wp = self.n0 * self.L / self.Np

        self.field_energy_history = []
        self.momentum_history = []
        self.time_history = []

    def initialize_two_stream(self):
        N_half = self.Np // 2
        x1 = np.linspace(0, self.L, N_half, endpoint=False)
        x2 = np.linspace(0, self.L, N_half, endpoint=False)
        k = 2 * np.pi * self.perturbation_mode / self.L
        x1 += self.perturbation_amp * np.sin(k * x1)
        x2 += self.perturbation_amp * np.sin(k * x2)
        v1 = np.full(N_half, self.v0)
        v2 = np.full(N_half, -self.v0)
        self.x = np.concatenate([x1, x2])
        self.v = np.concatenate([v1, v2])
        self.apply_periodic_bc()

    def initialize_langmuir(self):
        self.x = np.linspace(0, self.L, self.Np, endpoint=False)
        k = 2 * np.pi * self.perturbation_mode / self.L
        self.x += self.perturbation_amp * np.sin(k * self.x)
        self.v = np.zeros(self.Np)
        self.apply_periodic_bc()

    def deposit_charge(self):
        n_e = np.zeros(self.Ng)
        cell_pos = self.x / self.dx
        j_left = np.floor(cell_pos).astype(int) % self.Ng
        frac = cell_pos - np.floor(cell_pos)
        j_right = (j_left + 1) % self.Ng
        np.add.at(n_e, j_left, self.wp * (1.0 - frac) / self.dx)
        np.add.at(n_e, j_right, self.wp * frac / self.dx)
        return self.n0 - n_e

    def solve_poisson(self, rho):
        rho_hat = fft(rho)
        k = 2 * np.pi * fftfreq(self.Ng, d=self.dx)
        phi_hat = np.zeros_like(rho_hat)
        phi_hat[1:] = rho_hat[1:] / (k[1:]**2)
        phi_hat[0] = 0.0
        return np.real(ifft(phi_hat))

    def compute_electric_field(self, phi):
        return -(np.roll(phi, -1) - np.roll(phi, 1)) / (2.0 * self.dx)

    def interpolate_field_to_particles(self, E_grid):
        cell_pos = self.x / self.dx
        j_left = np.floor(cell_pos).astype(int) % self.Ng
        frac = cell_pos - np.floor(cell_pos)
        j_right = (j_left + 1) % self.Ng
        return (1.0 - frac) * E_grid[j_left] + frac * E_grid[j_right]

    def push_particles(self, E_particles):
        self.v += self.qm * E_particles * self.dt
        self.x += self.v * self.dt
        self.apply_periodic_bc()

    def apply_periodic_bc(self):
        self.x = self.x % self.L

    def compute_diagnostics(self, E_grid):
        field_energy = 0.5 * self.dx * np.sum(E_grid**2)
        self.field_energy_history.append(field_energy)
        self.momentum_history.append(np.sum(self.v * self.wp))

    def step(self):
        rho = self.deposit_charge()
        phi = self.solve_poisson(rho)
        E_grid = self.compute_electric_field(phi)
        E_particles = self.interpolate_field_to_particles(E_grid)
        self.push_particles(E_particles)
        self.compute_diagnostics(E_grid)

    def initialize_leapfrog(self):
        rho = self.deposit_charge()
        phi = self.solve_poisson(rho)
        E_grid = self.compute_electric_field(phi)
        E_particles = self.interpolate_field_to_particles(E_grid)
        self.v -= self.qm * E_particles * self.dt / 2

    def run(self, N_steps, initialize_func=None):
        if initialize_func == 'two_stream':
            self.initialize_two_stream()
        elif initialize_func == 'langmuir':
            self.initialize_langmuir()
        self.initialize_leapfrog()
        rho = self.deposit_charge()
        phi = self.solve_poisson(rho)
        E_grid = self.compute_electric_field(phi)
        self.compute_diagnostics(E_grid)
        self.time_history.append(0.0)
        for n in range(N_steps):
            self.step()
            self.time_history.append((n + 1) * self.dt)
        return {
            'time': np.array(self.time_history),
            'field_energy': np.array(self.field_energy_history),
            'momentum': np.array(self.momentum_history),
        }
'''

with open('/app/pic_framework.py', 'w') as f:
    f.write(corrected_code)

print("Corrected PIC framework written to /app/pic_framework.py")
