"""
1D Electrostatic Particle-in-Cell (PIC) Simulation Framework

Implements the core PIC algorithm for simulating collisionless plasma dynamics:
1. Deposit particle charges onto grid (CIC interpolation via C kernel)
2. Solve Poisson's equation for electrostatic potential (spectral method)
3. Compute electric field from potential (finite differences)
4. Interpolate field to particle positions (CIC interpolation via C kernel)
5. Advance particles using leapfrog time integration

Uses normalized units: epsilon_0 = 1, |q_e| = 1, m_e = 1
With background density n0 = 1, this gives plasma frequency omega_p = 1.

Particle weight: wp = n0 * L / N_particles (so deposited density matches n0)

Performance-critical kernels (charge deposition, field interpolation) are
implemented in C (/app/src/pic_kernels.c) and loaded via ctypes from
/app/lib/libpic_kernels.so. Build with `make` in /app/ before running.
"""

import ctypes
import os
import numpy as np
from numpy.fft import fft, ifft, fftfreq


class PICSimulation:
    def __init__(self, L, N_grid, N_particles, dt, v0=0.0,
                 perturbation_amp=0.0, perturbation_mode=1):
        """
        Initialize PIC simulation.

        Parameters
        ----------
        L : float
            Domain length (periodic).
        N_grid : int
            Number of grid points.
        N_particles : int
            Total number of simulation particles.
        dt : float
            Time step.
        v0 : float
            Beam velocity (for two-stream: beams at +/- v0).
        perturbation_amp : float
            Amplitude of initial sinusoidal position perturbation.
        perturbation_mode : int
            Mode number of perturbation (wavenumber k = 2*pi*mode/L).
        """
        self.L = L
        self.Ng = N_grid
        self.Np = N_particles
        self.dt = dt
        self.dx = L / N_grid
        self.v0 = v0
        self.perturbation_amp = perturbation_amp
        self.perturbation_mode = perturbation_mode

        self.x_grid = np.linspace(0, L, N_grid, endpoint=False)
        self.x = None  # particle positions
        self.v = None  # particle velocities

        # Charge-to-mass ratio for electrons (q_e / m_e = -1 in normalized units)
        self.qm = -1.0

        # Physical background ion density (n0 = 1 for omega_p = 1)
        self.n0 = 1.0

        # Particle weight: each simulation particle represents wp physical particles
        self.wp = self.n0 * self.L / self.Np

        # Diagnostics storage
        self.field_energy_history = []
        self.momentum_history = []
        self.time_history = []

        # Load C kernels for performance-critical operations
        lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                'lib', 'libpic_kernels.so')
        if not os.path.exists(lib_path):
            raise FileNotFoundError(
                f"C kernel library not found at {lib_path}. "
                f"Build it first: run 'make' in /app/"
            )
        self._lib = ctypes.CDLL(lib_path)

        # Configure C function signatures for cic_deposit
        self._lib.cic_deposit.argtypes = [
            ctypes.POINTER(ctypes.c_double),   # n_e (output)
            ctypes.POINTER(ctypes.c_double),   # x (input)
            ctypes.c_int,                       # N_particles
            ctypes.c_int,                       # N_grid
            ctypes.c_double,                    # dx
            ctypes.c_double,                    # L
            ctypes.c_double,                    # wp
        ]
        self._lib.cic_deposit.restype = None

        # Configure C function signatures for cic_interpolate
        self._lib.cic_interpolate.argtypes = [
            ctypes.POINTER(ctypes.c_double),   # E_particles (output)
            ctypes.POINTER(ctypes.c_double),   # E_grid (input)
            ctypes.POINTER(ctypes.c_double),   # x (input)
            ctypes.c_int,                       # N_particles
            ctypes.c_int,                       # N_grid
            ctypes.c_double,                    # dx
        ]
        self._lib.cic_interpolate.restype = None

    def initialize_two_stream(self):
        """Initialize two counter-streaming electron beams with perturbation.

        Creates N_particles/2 particles per beam. Beam 1 moves at +v0,
        beam 2 moves at -v0. A sinusoidal position perturbation seeds the
        instability.
        """
        N_half = self.Np // 2

        x1 = np.linspace(0, self.L, N_half, endpoint=False)
        x2 = np.linspace(0, self.L, N_half, endpoint=False)

        k = 2 * np.pi * self.perturbation_mode / self.L
        x1 += self.perturbation_amp * np.sin(k * x1)
        x2 += self.perturbation_amp * np.sin(k * x2)

        v1 = np.full(N_half, self.v0)
        v2 = np.full(N_half, self.v0)

        self.x = np.concatenate([x1, x2])
        self.v = np.concatenate([v1, v2])
        self.apply_periodic_bc()

    def initialize_langmuir(self):
        """Initialize uniform plasma with small sinusoidal density perturbation.

        All particles start at rest. A position perturbation creates a
        charge density modulation that drives plasma oscillations at omega_p.
        """
        self.x = np.linspace(0, self.L, self.Np, endpoint=False)
        k = 2 * np.pi * self.perturbation_mode / self.L
        self.x += self.perturbation_amp * np.sin(k * self.x)
        self.v = np.zeros(self.Np)
        self.apply_periodic_bc()

    def deposit_charge(self):
        """
        Deposit particle charges onto the grid using the C cic_deposit kernel
        and return the net charge density array.

        Call self._lib.cic_deposit to compute the electron number density n_e
        on the grid, then return rho = n0 - n_e.

        The C function signature is:
            void cic_deposit(double *n_e, const double *x, int N_particles,
                            int N_grid, double dx, double L, double wp)

        Use numpy ctypes interface to pass array pointers:
            arr.ctypes.data_as(ctypes.POINTER(ctypes.c_double))

        Returns
        -------
        rho : ndarray of shape (Ng,)
            Net charge density on the grid.
        """
        raise NotImplementedError("deposit_charge must be implemented using the C kernel")

    def solve_poisson(self, rho):
        """
        Solve Poisson's equation for the electrostatic potential using FFT.

        Poisson's equation: nabla^2 phi = -rho / epsilon_0 = -rho  (epsilon_0=1)

        In Fourier space: -k^2 * phi_hat = -rho_hat
        Therefore: phi_hat(k) = rho_hat(k) / k^2  for k != 0
                   phi_hat(0) = 0  (zero mean potential)

        Parameters
        ----------
        rho : ndarray of shape (Ng,)
            Charge density on the grid.

        Returns
        -------
        phi : ndarray of shape (Ng,)
            Electrostatic potential on the grid.
        """
        rho_hat = fft(rho)
        k = 2 * np.pi * fftfreq(self.Ng, d=self.dx)

        phi_hat = np.zeros_like(rho_hat)
        phi_hat[1:] = rho_hat[1:] / np.abs(k[1:])
        phi_hat[0] = 0.0

        return np.real(ifft(phi_hat))

    def compute_electric_field(self, phi):
        """
        Compute the electric field from the potential using central finite
        differences with periodic boundary conditions:

            E_j = -(phi_{j+1} - phi_{j-1}) / (2 * dx)

        Use np.roll for periodic boundary handling.

        Parameters
        ----------
        phi : ndarray of shape (Ng,)
            Electrostatic potential on the grid.

        Returns
        -------
        E : ndarray of shape (Ng,)
            Electric field on the grid.
        """
        raise NotImplementedError("compute_electric_field must be implemented")

    def interpolate_field_to_particles(self, E_grid):
        """
        Interpolate the electric field from grid points to particle positions
        using the C cic_interpolate kernel.

        The C function signature is:
            void cic_interpolate(double *E_particles, const double *E_grid,
                                const double *x, int N_particles,
                                int N_grid, double dx)

        Using the same interpolation kernel for deposition and interpolation
        ensures momentum conservation (Newton's third law in the PIC scheme).

        Parameters
        ----------
        E_grid : ndarray of shape (Ng,)
            Electric field on the grid.

        Returns
        -------
        E_particles : ndarray of shape (Np,)
            Electric field at each particle position.
        """
        raise NotImplementedError("interpolate_field_to_particles must be implemented using the C kernel")

    def push_particles(self, E_particles):
        """Advance particles using leapfrog integration.

        Leapfrog scheme:
            v(t + dt/2) = v(t - dt/2) + (q/m) * E(t) * dt
            x(t + dt)   = x(t) + v(t + dt/2) * dt
        """
        self.v += self.qm * E_particles * self.dt
        self.x += self.v * self.dt
        self.apply_periodic_bc()

    def apply_periodic_bc(self):
        """Apply periodic boundary conditions to particle positions."""
        self.x = self.x % self.L

    def compute_diagnostics(self, E_grid):
        """Compute and store field energy and total momentum."""
        field_energy = 0.5 * self.dx * np.sum(E_grid**2)
        self.field_energy_history.append(field_energy)
        self.momentum_history.append(np.sum(self.v * self.wp))

    def step(self):
        """Execute one full PIC cycle: deposit -> solve -> E-field -> interpolate -> push."""
        rho = self.deposit_charge()
        phi = self.solve_poisson(rho)
        E_grid = self.compute_electric_field(phi)
        E_particles = self.interpolate_field_to_particles(E_grid)
        self.push_particles(E_particles)
        self.compute_diagnostics(E_grid)

    def initialize_leapfrog(self):
        """Push velocities back by dt/2 to set up the leapfrog time offset.

        In leapfrog integration, positions and velocities are staggered by
        half a time step. This method creates that offset from synchronized
        initial conditions.
        """
        rho = self.deposit_charge()
        phi = self.solve_poisson(rho)
        E_grid = self.compute_electric_field(phi)
        E_particles = self.interpolate_field_to_particles(E_grid)
        self.v -= self.qm * E_particles * self.dt / 2

    def run(self, N_steps, initialize_func=None):
        """Run the full PIC simulation.

        Parameters
        ----------
        N_steps : int
            Number of time steps to advance.
        initialize_func : str, optional
            'two_stream' or 'langmuir' to set initial conditions.

        Returns
        -------
        dict with keys 'time', 'field_energy', 'momentum' (all ndarrays).
        """
        if initialize_func == 'two_stream':
            self.initialize_two_stream()
        elif initialize_func == 'langmuir':
            self.initialize_langmuir()

        # Set up leapfrog half-step offset
        self.initialize_leapfrog()

        # Record initial diagnostics at t=0
        rho = self.deposit_charge()
        phi = self.solve_poisson(rho)
        E_grid = self.compute_electric_field(phi)
        self.compute_diagnostics(E_grid)
        self.time_history.append(0.0)

        # Main time-stepping loop
        for n in range(N_steps):
            self.step()
            self.time_history.append((n + 1) * self.dt)

        return {
            'time': np.array(self.time_history),
            'field_energy': np.array(self.field_energy_history),
            'momentum': np.array(self.momentum_history),
        }
