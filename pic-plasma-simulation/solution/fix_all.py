#!/usr/bin/env python3
"""
Fix all bugs and implement missing methods in the PIC simulation framework.

Fixes applied:
1. C kernel (pic_kernels.c): cic_deposit has missing periodic boundary wrapping
   for j_right. Must use (j_left + 1) % N_grid instead of j_left + 1, otherwise
   particles near the domain boundary write out of bounds.

2. Makefile: Output target is pic_kernels.so but Python framework loads
   libpic_kernels.so. Fix the target name to include the lib prefix.

3. Python framework (pic_framework.py):
   a. Poisson solver uses np.abs(k) (magnitude) instead of k**2 (Laplacian in
      Fourier space). This gives correct results only for k=1, wrong for k>1.
   b. Two-stream initialization sets both beams to +v0 instead of +/-v0,
      producing a single drifting beam with no counter-streaming instability.
   c. Three methods must be implemented:
      - deposit_charge: call C cic_deposit via ctypes
      - compute_electric_field: central finite differences with np.roll
      - interpolate_field_to_particles: call C cic_interpolate via ctypes

4. gnuplot script: Output path is phase_plot.png instead of phase_space.png.
"""

# --- Fix 1: C kernel periodic boundary bug ---
with open('/app/src/pic_kernels.c', 'r') as f:
    c_code = f.read()

c_code = c_code.replace(
    'j_right = j_left + 1;',
    'j_right = (j_left + 1) % N_grid;'
)

with open('/app/src/pic_kernels.c', 'w') as f:
    f.write(c_code)

print("Fixed C kernel: added periodic boundary wrapping in cic_deposit")

# --- Fix 2: Makefile output filename ---
with open('/app/Makefile', 'r') as f:
    makefile = f.read()

makefile = makefile.replace('pic_kernels.so', 'libpic_kernels.so')

with open('/app/Makefile', 'w') as f:
    f.write(makefile)

print("Fixed Makefile: corrected output filename to libpic_kernels.so")

# --- Fix 3: gnuplot output path ---
with open('/app/plot_phase_space.gp', 'r') as f:
    gp_script = f.read()

gp_script = gp_script.replace('phase_plot.png', 'phase_space.png')

with open('/app/plot_phase_space.gp', 'w') as f:
    f.write(gp_script)

print("Fixed gnuplot script: corrected output path to phase_space.png")

# --- Fix 4: Python PIC framework (bugs + implementations) ---
corrected_framework = '''"""
1D Electrostatic Particle-in-Cell (PIC) Simulation Framework

Uses normalized units: epsilon_0 = 1, |q_e| = 1, m_e = 1
With background density n0 = 1, plasma frequency omega_p = 1.
Particle weight: wp = n0 * L / N_particles

C kernels loaded from /app/lib/libpic_kernels.so via ctypes.
"""

import ctypes
import os
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

        # Load C kernels
        lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                'lib', 'libpic_kernels.so')
        if not os.path.exists(lib_path):
            raise FileNotFoundError(
                f"C kernel library not found at {lib_path}. "
                f"Build it first: run 'make' in /app/"
            )
        self._lib = ctypes.CDLL(lib_path)

        self._lib.cic_deposit.argtypes = [
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.c_int, ctypes.c_int,
            ctypes.c_double, ctypes.c_double, ctypes.c_double,
        ]
        self._lib.cic_deposit.restype = None

        self._lib.cic_interpolate.argtypes = [
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.c_int, ctypes.c_int, ctypes.c_double,
        ]
        self._lib.cic_interpolate.restype = None

    def initialize_two_stream(self):
        N_half = self.Np // 2
        x1 = np.linspace(0, self.L, N_half, endpoint=False)
        x2 = np.linspace(0, self.L, N_half, endpoint=False)
        k = 2 * np.pi * self.perturbation_mode / self.L
        x1 += self.perturbation_amp * np.sin(k * x1)
        x2 += self.perturbation_amp * np.sin(k * x2)
        v1 = np.full(N_half, self.v0)
        v2 = np.full(N_half, -self.v0)  # Counter-streaming: beam 2 at -v0
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
        n_e = np.zeros(self.Ng, dtype=np.float64)
        x_arr = np.ascontiguousarray(self.x, dtype=np.float64)
        self._lib.cic_deposit(
            n_e.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
            x_arr.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
            ctypes.c_int(self.Np),
            ctypes.c_int(self.Ng),
            ctypes.c_double(self.dx),
            ctypes.c_double(self.L),
            ctypes.c_double(self.wp)
        )
        return self.n0 - n_e

    def solve_poisson(self, rho):
        rho_hat = fft(rho)
        k = 2 * np.pi * fftfreq(self.Ng, d=self.dx)
        phi_hat = np.zeros_like(rho_hat)
        phi_hat[1:] = rho_hat[1:] / (k[1:]**2)  # Laplacian: k-squared
        phi_hat[0] = 0.0
        return np.real(ifft(phi_hat))

    def compute_electric_field(self, phi):
        return -(np.roll(phi, -1) - np.roll(phi, 1)) / (2.0 * self.dx)

    def interpolate_field_to_particles(self, E_grid):
        E_particles = np.zeros(self.Np, dtype=np.float64)
        E_grid_arr = np.ascontiguousarray(E_grid, dtype=np.float64)
        x_arr = np.ascontiguousarray(self.x, dtype=np.float64)
        self._lib.cic_interpolate(
            E_particles.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
            E_grid_arr.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
            x_arr.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
            ctypes.c_int(self.Np),
            ctypes.c_int(self.Ng),
            ctypes.c_double(self.dx)
        )
        return E_particles

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
    f.write(corrected_framework)

print("Fixed Python framework: implemented ctypes wrappers, fixed Poisson and two-stream bugs")
