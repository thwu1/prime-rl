"""Pseudo-spectral 2D incompressible Navier-Stokes solver.

Vorticity-streamfunction formulation on doubly-periodic [0, 2pi]^2 domain.
FFT-based spatial operators, SSP-RK3 time integration, 2/3-rule dealiasing.
"""

import numpy as np
from numpy.fft import fft2, ifft2, fftfreq


class NS2DSolver:
    def __init__(self, N, Re, dt, dealias=True):
        self.N = N
        self.Re = Re
        self.nu = 0.0 if Re == float("inf") else 1.0 / Re
        self.dt = dt

        # Physical grid on [0, 2pi)
        x = np.linspace(0, 2.0 * np.pi, N, endpoint=False)
        self.X, self.Y = np.meshgrid(x, x, indexing="ij")

        # Integer wavenumbers for 2pi-periodic domain
        k = fftfreq(N, d=1.0 / N)
        self.KX, self.KY = np.meshgrid(k, k, indexing="ij")
        self.K2 = self.KX**2 + self.KY**2
        self.K_mag = np.sqrt(self.K2)

        # Inverse Laplacian (Poisson solver); zero-mean mode excluded
        self.K2_inv = np.zeros((N, N))
        nz = self.K2 > 0
        self.K2_inv[nz] = 1.0 / self.K2[nz]

        # 2/3 dealiasing mask
        self._dealias = dealias
        kmax = N // 3
        self.mask = np.ones((N, N), dtype=float)
        if dealias:
            self.mask[(np.abs(self.KX) > kmax) | (np.abs(self.KY) > kmax)] = 0.0

    # ------------------------------------------------------------------ init
    def initialize_taylor_green(self):
        """Return omega = 2 cos(x) cos(y)."""
        return 2.0 * np.cos(self.X) * np.cos(self.Y)

    # --------------------------------------------------------- spatial ops
    def solve_poisson(self, omega):
        """Solve laplacian(psi) = -omega  =>  psi_hat = omega_hat / K^2."""
        return np.real(ifft2(fft2(omega) * self.K2_inv))

    def compute_velocity(self, psi):
        """u = dpsi/dy, v = -dpsi/dx via spectral differentiation."""
        psi_hat = fft2(psi)
        u = np.real(ifft2(1j * self.KY * psi_hat))
        v = np.real(ifft2(-1j * self.KX * psi_hat))
        return u, v

    # ---------------------------------------------------------- RHS & step
    def _rhs(self, omega):
        """Compute d(omega)/dt = -u . grad(omega) + nu * laplacian(omega)."""
        omega_hat = fft2(omega)

        # Dealias input for nonlinear term computation
        wh = omega_hat * self.mask

        # Streamfunction and velocity from dealiased vorticity
        psi_hat = wh * self.K2_inv
        u = np.real(ifft2(1j * self.KY * psi_hat))
        v = np.real(ifft2(-1j * self.KX * psi_hat))

        # Vorticity gradients from dealiased vorticity
        dwdx = np.real(ifft2(1j * self.KX * wh))
        dwdy = np.real(ifft2(1j * self.KY * wh))

        # Nonlinear advection in physical space, then dealias product
        nl_hat = fft2(u * dwdx + v * dwdy) * self.mask

        # Diffusion from full (unmasked) vorticity spectrum
        diff_hat = -self.nu * self.K2 * omega_hat

        return np.real(ifft2(-nl_hat + diff_hat))

    def step(self, omega):
        """SSP-RK3 Shu-Osher form:
        w1 = w  + dt * L(w)
        w2 = 3/4 w + 1/4 w1 + 1/4 dt * L(w1)
        w3 = 1/3 w + 2/3 w2 + 2/3 dt * L(w2)
        """
        dt = self.dt
        L1 = self._rhs(omega)
        w1 = omega + dt * L1

        L2 = self._rhs(w1)
        w2 = 0.75 * omega + 0.25 * (w1 + dt * L2)

        L3 = self._rhs(w2)
        return (1.0 / 3.0) * omega + (2.0 / 3.0) * (w2 + dt * L3)

    # -------------------------------------------------------- diagnostics
    def compute_energy(self, omega):
        """Domain-averaged kinetic energy E = <|u|^2> / 2."""
        psi = self.solve_poisson(omega)
        u, v = self.compute_velocity(psi)
        return 0.5 * np.mean(u**2 + v**2)

    def compute_enstrophy(self, omega):
        """Domain-averaged enstrophy Z = <omega^2> / 2."""
        return 0.5 * np.mean(omega**2)

    def compute_energy_spectrum(self, omega):
        """Shell-summed 1D energy spectrum E(k).

        E(k) = (1/2) * (1/N^4) * sum_{k <= |kappa| < k+1} |omega_hat|^2 / |kappa|^2
        Total energy = sum_k E(k).
        """
        omega_hat = fft2(omega)
        N = self.N
        power = np.abs(omega_hat) ** 2
        kmax_shell = int(np.sqrt(2) * N / 2) + 1
        spectrum = np.zeros(kmax_shell)
        for ki in range(1, kmax_shell):
            shell = (self.K_mag >= ki) & (self.K_mag < ki + 1)
            if np.any(shell):
                spectrum[ki] = 0.5 / N**4 * np.sum(power[shell] / self.K2[shell])
        return spectrum

    # ----------------------------------------------------------- run
    def run(self, omega, T):
        """Integrate from current state to time T.

        Returns dict with 'omega' (final field), 'times', 'energies',
        'enstrophies' (1D arrays including t=0).
        """
        nsteps = int(round(T / self.dt))
        times = [0.0]
        energies = [self.compute_energy(omega)]
        enstrophies = [self.compute_enstrophy(omega)]
        for i in range(nsteps):
            omega = self.step(omega)
            times.append((i + 1) * self.dt)
            energies.append(self.compute_energy(omega))
            enstrophies.append(self.compute_enstrophy(omega))
        return {
            "omega": omega,
            "times": np.array(times),
            "energies": np.array(energies),
            "enstrophies": np.array(enstrophies),
        }
