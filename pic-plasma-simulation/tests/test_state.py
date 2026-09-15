
"""
Tests for the 1D electrostatic PIC plasma simulation.

Verifies:
- Build system produces loadable C shared library
- Unit correctness of individual PIC components (charge deposition, Poisson solver)
- Integration tests comparing full simulation output to analytic predictions
  (Langmuir oscillation frequency, two-stream instability growth rate)
- gnuplot phase-space visualization output
"""

import ctypes
import json
import os
import subprocess
import sys

import numpy as np
import pytest

sys.path.insert(0, '/app')


class TestBuildSystem:
    """Verify the C kernel shared library is built and loadable."""

    def test_shared_library_exists(self):
        """The compiled C kernel library must be present at the expected path."""
        assert os.path.exists('/app/lib/libpic_kernels.so'), \
            "C kernel library not found at /app/lib/libpic_kernels.so. Run 'make' in /app/"

    def test_shared_library_loadable(self):
        """The C kernel library must be loadable via ctypes with expected symbols."""
        lib = ctypes.CDLL('/app/lib/libpic_kernels.so')
        # These raise AttributeError if the symbols don't exist
        lib.cic_deposit
        lib.cic_interpolate


class TestChargeDeposition:
    """Test the CIC charge deposition method."""

    def test_uniform_gives_neutral(self):
        """Uniformly spaced particles should produce near-zero net charge."""
        from pic_framework import PICSimulation

        sim = PICSimulation(L=2 * np.pi, N_grid=32, N_particles=3200, dt=0.01)
        sim.x = np.linspace(0, sim.L, sim.Np, endpoint=False)
        sim.v = np.zeros(sim.Np)

        rho = sim.deposit_charge()
        assert rho is not None, "deposit_charge returned None"
        assert len(rho) == sim.Ng, f"Wrong grid size: {len(rho)} vs {sim.Ng}"
        assert np.max(np.abs(rho)) < 0.01, \
            f"Uniform plasma not neutral: max|rho| = {np.max(np.abs(rho)):.6f}"

    def test_perturbed_has_correct_mode(self):
        """Sinusoidal position perturbation should produce mode-1 charge density."""
        from pic_framework import PICSimulation

        Ng = 64
        Np = 64000
        L = 2 * np.pi
        sim = PICSimulation(L=L, N_grid=Ng, N_particles=Np, dt=0.01)

        sim.x = np.linspace(0, L, Np, endpoint=False)
        k = 2 * np.pi / L
        sim.x += 0.01 * np.sin(k * sim.x)
        sim.x = sim.x % L
        sim.v = np.zeros(Np)

        rho = sim.deposit_charge()
        rho_hat = np.abs(np.fft.rfft(rho))
        # Mode 1 should dominate (excluding DC)
        dominant = np.argmax(rho_hat[1:]) + 1
        assert dominant == 1, f"Dominant mode is {dominant}, expected 1"


class TestPoissonSolver:
    """Test the spectral Poisson solver."""

    def test_sinusoidal_k1(self):
        """Known analytic: rho = sin(x) -> phi = sin(x)/1 = sin(x)."""
        from pic_framework import PICSimulation

        sim = PICSimulation(L=2 * np.pi, N_grid=64, N_particles=100, dt=0.01)

        k = 1.0
        x = sim.x_grid
        rho = np.sin(k * x)
        phi = sim.solve_poisson(rho)
        phi_exact = np.sin(k * x) / k**2  # = sin(x)

        error = np.max(np.abs(phi - phi_exact))
        assert error < 1e-10, \
            f"Poisson solver error for sin(x): {error:.2e} (expected < 1e-10)"

    def test_sinusoidal_k3(self):
        """Known analytic: rho = sin(3x) -> phi = sin(3x)/9."""
        from pic_framework import PICSimulation

        sim = PICSimulation(L=2 * np.pi, N_grid=64, N_particles=100, dt=0.01)

        k = 3.0
        x = sim.x_grid
        rho = np.sin(k * x)
        phi = sim.solve_poisson(rho)
        phi_exact = np.sin(k * x) / k**2

        error = np.max(np.abs(phi - phi_exact))
        assert error < 1e-10, \
            f"Poisson solver error for sin(3x): {error:.2e} (expected < 1e-10)"

    def test_cosine_k5(self):
        """Known analytic: rho = cos(5x) -> phi = cos(5x)/25."""
        from pic_framework import PICSimulation

        sim = PICSimulation(L=2 * np.pi, N_grid=64, N_particles=100, dt=0.01)

        k = 5.0
        x = sim.x_grid
        rho = np.cos(k * x)
        phi = sim.solve_poisson(rho)
        phi_exact = np.cos(k * x) / k**2

        error = np.max(np.abs(phi - phi_exact))
        assert error < 1e-10, \
            f"Poisson solver error for cos(5x): {error:.2e} (expected < 1e-10)"


class TestLangmuirOscillation:
    """Integration test: Langmuir plasma oscillation frequency."""

    def test_oscillation_frequency(self):
        """Measured omega_p should match expected value within 5%."""
        result = subprocess.run(
            ['python3', '/app/run_langmuir.py'],
            capture_output=True, text=True, timeout=180, cwd='/app'
        )
        assert result.returncode == 0, \
            f"Langmuir simulation failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"

        with open('/app/output/langmuir_results.json') as f:
            data = json.load(f)

        omega = data['omega_p_measured']
        err = data['relative_error']
        assert err < 0.05, \
            f"Langmuir omega_p error too large: measured={omega:.4f}, expected=1.0, err={err:.4f}"

    def test_momentum_conservation(self):
        """Total momentum should be conserved in Langmuir oscillation test."""
        if not os.path.exists('/app/output/langmuir_results.json'):
            subprocess.run(
                ['python3', '/app/run_langmuir.py'],
                capture_output=True, text=True, timeout=180, cwd='/app'
            )

        with open('/app/output/langmuir_results.json') as f:
            data = json.load(f)

        merr = data['max_momentum_error']
        assert merr < 1e-6, \
            f"Momentum not conserved: max error = {merr:.2e}"


class TestTwoStreamInstability:
    """Integration test: two-stream instability growth rate."""

    def test_growth_rate(self):
        """Measured growth rate should match analytic prediction within 15%."""
        result = subprocess.run(
            ['python3', '/app/run_two_stream.py'],
            capture_output=True, text=True, timeout=300, cwd='/app'
        )
        assert result.returncode == 0, \
            f"Two-stream simulation failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"

        with open('/app/output/two_stream_results.json') as f:
            data = json.load(f)

        gamma_m = data['growth_rate_measured']
        gamma_a = data['growth_rate_analytic']
        err = data['relative_error']

        assert gamma_m > 0, f"Growth rate should be positive: {gamma_m:.6f}"
        assert err < 0.15, \
            f"Growth rate error: measured={gamma_m:.4f}, analytic={gamma_a:.4f}, err={err:.2%}"

    def test_energy_growth(self):
        """Field energy should grow substantially during the instability."""
        if not os.path.exists('/app/output/two_stream_results.json'):
            subprocess.run(
                ['python3', '/app/run_two_stream.py'],
                capture_output=True, text=True, timeout=300, cwd='/app'
            )

        with open('/app/output/two_stream_results.json') as f:
            data = json.load(f)

        ratio = data['final_field_energy'] / (data['initial_field_energy'] + 1e-50)
        assert ratio > 10, \
            f"Field energy didn't grow enough: ratio = {ratio:.1f} (expected >> 10)"


class TestPhaseSpacePlot:
    """Verify gnuplot produces the phase-space visualization."""

    def test_gnuplot_produces_png(self):
        """gnuplot must produce a valid PNG from simulation phase-space data."""
        # Ensure simulation data exists
        if not os.path.exists('/app/output/phase_space.dat'):
            result = subprocess.run(
                ['python3', '/app/run_two_stream.py'],
                capture_output=True, text=True, timeout=300, cwd='/app'
            )
            assert result.returncode == 0, \
                f"Two-stream simulation failed: {result.stderr}"

        # Verify data file has expected format (2 columns)
        data = np.loadtxt('/app/output/phase_space.dat')
        assert data.ndim == 2 and data.shape[1] == 2, \
            f"phase_space.dat should have 2 columns, got shape {data.shape}"

        # Run gnuplot script
        result = subprocess.run(
            ['gnuplot', '/app/plot_phase_space.gp'],
            capture_output=True, text=True, timeout=30, cwd='/app'
        )
        assert result.returncode == 0, \
            f"gnuplot failed: {result.stderr}"

        # Check PNG exists at the expected path
        assert os.path.exists('/app/output/phase_space.png'), \
            "Phase-space plot not generated at /app/output/phase_space.png"
