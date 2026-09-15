
import pytest
import json
import os
import numpy as np


def _solve_riemann_star(rho_L, u_L, p_L, rho_R, u_R, p_R, gamma):
    """Independent reference computation of star-region pressure and velocity."""
    a_L = np.sqrt(gamma * p_L / rho_L)
    a_R = np.sqrt(gamma * p_R / rho_R)

    g1 = (gamma - 1.0) / (2.0 * gamma)
    g2 = (gamma + 1.0) / (2.0 * gamma)
    g4 = 2.0 / (gamma - 1.0)
    g5 = 2.0 / (gamma + 1.0)
    g6 = (gamma - 1.0) / (gamma + 1.0)

    # PVRS initial guess
    p_star = max(
        0.5 * (p_L + p_R)
        - 0.125 * (u_R - u_L) * (rho_L + rho_R) * (a_L + a_R),
        1e-10,
    )

    for _ in range(300):
        # Left wave
        if p_star <= p_L:
            ratio = p_star / p_L
            f_L = g4 * a_L * (ratio ** g1 - 1.0)
            fp_L = (1.0 / (rho_L * a_L)) * ratio ** (-g2)
        else:
            A_L = g5 / rho_L
            B_L = g6 * p_L
            sqr = np.sqrt(A_L / (p_star + B_L))
            f_L = (p_star - p_L) * sqr
            fp_L = sqr * (1.0 - (p_star - p_L) / (2.0 * (p_star + B_L)))

        # Right wave
        if p_star <= p_R:
            ratio = p_star / p_R
            f_R = g4 * a_R * (ratio ** g1 - 1.0)
            fp_R = (1.0 / (rho_R * a_R)) * ratio ** (-g2)
        else:
            A_R = g5 / rho_R
            B_R = g6 * p_R
            sqr = np.sqrt(A_R / (p_star + B_R))
            f_R = (p_star - p_R) * sqr
            fp_R = sqr * (1.0 - (p_star - p_R) / (2.0 * (p_star + B_R)))

        f = f_L + f_R + (u_R - u_L)
        fp = fp_L + fp_R

        if abs(fp) < 1e-30:
            break

        dp = -f / fp
        p_new = max(p_star + dp, 1e-10)

        if 2.0 * abs(p_new - p_star) / (p_new + p_star + 1e-30) < 1e-12:
            p_star = p_new
            break
        p_star = p_new

    # Recompute f_L, f_R at converged p_star
    if p_star <= p_L:
        f_L = g4 * a_L * ((p_star / p_L) ** g1 - 1.0)
    else:
        A_L = g5 / rho_L
        B_L = g6 * p_L
        f_L = (p_star - p_L) * np.sqrt(A_L / (p_star + B_L))

    if p_star <= p_R:
        f_R = g4 * a_R * ((p_star / p_R) ** g1 - 1.0)
    else:
        A_R = g5 / rho_R
        B_R = g6 * p_R
        f_R = (p_star - p_R) * np.sqrt(A_R / (p_star + B_R))

    u_star = 0.5 * (u_L + u_R) + 0.5 * (f_R - f_L)

    return p_star, u_star


class TestRiemannSolverResults:
    """Verify the agent's Riemann solver and convergence study results."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Load results and compute independent reference values."""
        assert os.path.exists('/app/results.json'), \
            "results.json does not exist at /app/results.json"

        with open('/app/results.json', 'r') as f:
            self.results = json.load(f)

        # Problem parameters
        self.gamma = 1.4
        self.rho_L, self.u_L, self.p_L = 2.0, 0.0, 8.0
        self.rho_R, self.u_R, self.p_R = 1.0, 0.0, 1.0

        # Compute reference star region independently
        self.p_star_ref, self.u_star_ref = _solve_riemann_star(
            self.rho_L, self.u_L, self.p_L,
            self.rho_R, self.u_R, self.p_R,
            self.gamma,
        )

        # Reference wave speeds and star-region densities
        a_L = np.sqrt(self.gamma * self.p_L / self.rho_L)
        a_R = np.sqrt(self.gamma * self.p_R / self.rho_R)
        g1 = (self.gamma - 1.0) / (2.0 * self.gamma)
        g2 = (self.gamma + 1.0) / (2.0 * self.gamma)
        g6 = (self.gamma - 1.0) / (self.gamma + 1.0)

        # Left rarefaction (p_star < p_L for this problem)
        a_star_L = a_L * (self.p_star_ref / self.p_L) ** g1
        self.S_HL_ref = self.u_L - a_L
        self.S_TL_ref = self.u_star_ref - a_star_L
        self.rho_star_L_ref = self.rho_L * (self.p_star_ref / self.p_L) ** (1.0 / self.gamma)

        # Right shock (p_star > p_R for this problem)
        self.S_R_ref = self.u_R + a_R * np.sqrt(g2 * self.p_star_ref / self.p_R + g1)
        self.rho_star_R_ref = self.rho_R * (
            (self.p_star_ref / self.p_R + g6) / (g6 * self.p_star_ref / self.p_R + 1.0)
        )

    # --- Structure tests ---

    def test_results_file_exists(self):
        assert os.path.exists('/app/results.json')

    def test_all_fields_present(self):
        required = [
            'p_star', 'u_star', 'rho_star_L', 'rho_star_R',
            'shock_speed', 'contact_speed',
            'rarefaction_head_speed', 'rarefaction_tail_speed',
            'convergence_order', 'gci_finest',
            'l2_error_density_N100', 'l2_error_density_N200',
            'l2_error_density_N400', 'l2_error_density_N800',
        ]
        for field in required:
            assert field in self.results, f"Missing required field: {field}"

    # --- Star-region accuracy tests ---

    def test_p_star(self):
        rel = abs(self.results['p_star'] - self.p_star_ref) / self.p_star_ref
        assert rel < 0.02, (
            f"p_star={self.results['p_star']:.6f}, ref={self.p_star_ref:.6f}, rel_err={rel:.4f}"
        )

    def test_u_star(self):
        rel = abs(self.results['u_star'] - self.u_star_ref) / abs(self.u_star_ref)
        assert rel < 0.02, (
            f"u_star={self.results['u_star']:.6f}, ref={self.u_star_ref:.6f}, rel_err={rel:.4f}"
        )

    def test_rho_star_L(self):
        rel = abs(self.results['rho_star_L'] - self.rho_star_L_ref) / self.rho_star_L_ref
        assert rel < 0.02, (
            f"rho_star_L={self.results['rho_star_L']:.6f}, ref={self.rho_star_L_ref:.6f}"
        )

    def test_rho_star_R(self):
        rel = abs(self.results['rho_star_R'] - self.rho_star_R_ref) / self.rho_star_R_ref
        assert rel < 0.02, (
            f"rho_star_R={self.results['rho_star_R']:.6f}, ref={self.rho_star_R_ref:.6f}"
        )

    # --- Wave speed tests ---

    def test_shock_speed(self):
        rel = abs(self.results['shock_speed'] - self.S_R_ref) / abs(self.S_R_ref)
        assert rel < 0.02, (
            f"shock_speed={self.results['shock_speed']:.6f}, ref={self.S_R_ref:.6f}"
        )

    def test_contact_speed(self):
        rel = abs(self.results['contact_speed'] - self.u_star_ref) / abs(self.u_star_ref)
        assert rel < 0.02, (
            f"contact_speed={self.results['contact_speed']:.6f}, ref={self.u_star_ref:.6f}"
        )

    def test_rarefaction_head_speed(self):
        rel = abs(self.results['rarefaction_head_speed'] - self.S_HL_ref) / abs(self.S_HL_ref)
        assert rel < 0.02, (
            f"S_HL={self.results['rarefaction_head_speed']:.6f}, ref={self.S_HL_ref:.6f}"
        )

    def test_rarefaction_tail_speed(self):
        rel = abs(self.results['rarefaction_tail_speed'] - self.S_TL_ref) / abs(self.S_TL_ref)
        assert rel < 0.05, (
            f"S_TL={self.results['rarefaction_tail_speed']:.6f}, ref={self.S_TL_ref:.6f}"
        )

    # --- Convergence study tests ---

    def test_convergence_order_reasonable(self):
        p = self.results['convergence_order']
        assert 0.2 <= p <= 2.5, f"Convergence order {p} outside expected range [0.2, 2.5]"

    def test_gci_positive(self):
        assert self.results['gci_finest'] > 0, "GCI must be positive"

    def test_gci_bounded(self):
        assert self.results['gci_finest'] < 5.0, (
            f"GCI={self.results['gci_finest']:.4f} unreasonably large"
        )

    def test_errors_decreasing(self):
        e100 = self.results['l2_error_density_N100']
        e200 = self.results['l2_error_density_N200']
        e400 = self.results['l2_error_density_N400']
        e800 = self.results['l2_error_density_N800']
        assert e100 > e200 > e400 > e800, (
            f"L2 errors must decrease: {e100:.4e} > {e200:.4e} > {e400:.4e} > {e800:.4e}"
        )

    def test_finest_mesh_accuracy(self):
        err = self.results['l2_error_density_N800']
        assert err < 0.20, f"L2 error on N=800 mesh too large: {err:.4e}"

    def test_coarsest_mesh_bounded(self):
        err = self.results['l2_error_density_N100']
        assert err < 1.0, f"L2 error on N=100 mesh unreasonable: {err:.4e}"

    def test_all_errors_positive(self):
        for N in [100, 200, 400, 800]:
            err = self.results[f'l2_error_density_N{N}']
            assert err > 0, f"L2 error for N={N} must be positive, got {err}"

    # --- Tool output verification tests ---

    def test_mesh_files_exist(self):
        """Verify gmsh was used to generate mesh files."""
        for N in [100, 200, 400, 800]:
            path = f'/app/mesh_N{N}.msh'
            assert os.path.exists(path), f"Mesh file {path} not found"
            size = os.path.getsize(path)
            assert size > 100, f"Mesh file {path} too small ({size} bytes)"

    def test_mesh_files_gmsh_format(self):
        """Verify mesh files contain gmsh format markers."""
        for N in [100, 200, 400, 800]:
            path = f'/app/mesh_N{N}.msh'
            with open(path) as f:
                content = f.read()
            assert '$MeshFormat' in content, (
                f"{path} missing $MeshFormat header - must be gmsh .msh format"
            )
            assert '$Nodes' in content, (
                f"{path} missing $Nodes section"
            )

    def test_convergence_data_file(self):
        """Verify convergence data file exists for gnuplot input."""
        path = '/app/convergence_data.dat'
        assert os.path.exists(path), f"{path} not found"
        with open(path) as f:
            lines = [l for l in f.readlines() if l.strip() and not l.strip().startswith('#')]
        assert len(lines) >= 4, (
            f"convergence_data.dat should have >= 4 data lines, found {len(lines)}"
        )

    def test_convergence_plot_exists(self):
        """Verify gnuplot produced a convergence plot."""
        path = '/app/convergence.png'
        assert os.path.exists(path), f"{path} not found"
        size = os.path.getsize(path)
        assert size > 1000, f"Plot file too small ({size} bytes), likely corrupt or empty"
