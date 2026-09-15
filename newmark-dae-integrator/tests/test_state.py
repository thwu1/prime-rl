"""
Tests for the spatial double pendulum DAE simulation.

"""

import json
import os
import sys
import pytest
import numpy as np

sys.path.insert(0, '/app/simulation')
sys.path.insert(0, '/app')


RESULTS_FILE = '/app/results/simulation_results.json'
TRAJ_FILE = '/app/results/trajectories.npz'


@pytest.fixture
def results():
    """Load simulation results."""
    if not os.path.exists(RESULTS_FILE):
        pytest.fail("Simulation results not found. Run run_simulation.py first.")
    with open(RESULTS_FILE) as f:
        return json.load(f)


@pytest.fixture
def trajectories():
    """Load trajectory data."""
    if not os.path.exists(TRAJ_FILE):
        pytest.fail("Trajectory data not found. Run run_simulation.py first.")
    return np.load(TRAJ_FILE)


class TestNativeLibrary:
    """Test that the native constraint library is built and functional."""

    def test_native_library_exists(self):
        """The native constraint library must be built as a shared object."""
        assert os.path.exists('/app/native/libconstraints.so'), (
            "Native library not found at /app/native/libconstraints.so"
        )

    def test_constraint_jacobian_nonzero(self):
        """Constraint Jacobian should not be all zeros."""
        import config
        from bodies import DoublePendulumSystem
        from constraints import compute_jacobian

        system = DoublePendulumSystem(config)
        system.set_initial_conditions()
        Phi_v = compute_jacobian(system)
        assert np.linalg.norm(Phi_v) > 0.1, (
            "Constraint Jacobian is all zeros — native library not working"
        )

    def test_iteration_matrix_nonsingular(self):
        """The assembled iteration matrix should be non-singular."""
        import config
        from bodies import DoublePendulumSystem
        from integrator import NewmarkBetaDAE

        system = DoublePendulumSystem(config)
        system.set_initial_conditions()
        integrator = NewmarkBetaDAE(system, config)
        A = integrator._assemble_iteration_matrix()
        assert np.linalg.norm(A) > 0.1, (
            "Iteration matrix is all zeros — _assemble_iteration_matrix() not implemented"
        )
        rank = np.linalg.matrix_rank(A)
        expected = system.n_vel + system.n_constraints
        assert rank == expected, (
            f"Iteration matrix rank {rank} < {expected} — matrix is singular"
        )


class TestSimulationCompletion:
    """Test that the simulation completes successfully."""

    def test_simulation_completed(self, results):
        """The simulation must complete all timesteps."""
        assert results['completed'], (
            f"Simulation failed after {results['n_steps_completed']}/{results['n_steps_total']} steps"
        )

    def test_all_steps_completed(self, results):
        """All 10000 steps must complete."""
        assert results['n_steps_completed'] == results['n_steps_total']


class TestConstraintSatisfaction:
    """Test that constraints are satisfied throughout the simulation."""

    def test_max_constraint_violation(self, results):
        """Maximum constraint violation must be below 1e-6."""
        max_viol = results['max_constraint_violation']
        assert max_viol < 1e-6, (
            f"Max constraint violation {max_viol:.2e} exceeds 1e-6"
        )

    def test_constraint_violation_trajectory(self, trajectories):
        """Constraint violations must stay below 1e-6 at every recorded step."""
        cv = trajectories['constraint_violations']
        max_cv = np.max(cv)
        assert max_cv < 1e-6, (
            f"Constraint violation exceeded 1e-6 during simulation (max: {max_cv:.2e})"
        )

    def test_quaternion_norms_link1(self, trajectories):
        """Quaternion norms for link 1 must remain near 1."""
        qn = trajectories['quat_norms_1']
        max_err = np.max(np.abs(qn - 1.0))
        assert max_err < 1e-4, (
            f"Link 1 quaternion norm deviation {max_err:.2e} exceeds 1e-4"
        )

    def test_quaternion_norms_link2(self, trajectories):
        """Quaternion norms for link 2 must remain near 1."""
        qn = trajectories['quat_norms_2']
        max_err = np.max(np.abs(qn - 1.0))
        assert max_err < 1e-4, (
            f"Link 2 quaternion norm deviation {max_err:.2e} exceeds 1e-4"
        )


class TestEnergyConservation:
    """Test energy conservation properties."""

    def test_final_energy_conservation(self, results):
        """Final energy must be within 2% of initial energy."""
        E0 = results['initial_energy']
        Ef = results['final_energy']
        rel_err = abs(Ef - E0) / abs(E0)
        assert rel_err < 0.02, (
            f"Final energy relative error {rel_err:.4f} exceeds 2%"
        )

    def test_energy_conservation_over_trajectory(self, trajectories):
        """Energy must stay within 2% of initial value throughout."""
        energies = trajectories['energies']
        E0 = energies[0]
        max_rel_err = np.max(np.abs(energies - E0) / abs(E0))
        assert max_rel_err < 0.02, (
            f"Max energy relative error {max_rel_err:.4f} exceeds 2% during simulation"
        )

    def test_energy_not_zero(self, results):
        """Energy values must be physically meaningful (nonzero)."""
        assert abs(results['initial_energy']) > 0.01, "Initial energy is suspiciously close to zero"
        assert abs(results['final_energy']) > 0.01, "Final energy is suspiciously close to zero"


class TestSolverConvergence:
    """Test solver convergence properties."""

    def test_average_iterations(self, results):
        """Average solver iterations per step must be reasonable."""
        avg = results['avg_newton_iterations']
        assert avg <= 10, (
            f"Average solver iterations {avg:.1f} exceeds 10 (poorly conditioned)"
        )

    def test_average_iterations_lower_bound(self, results):
        """Average iterations should be at least 1 (sanity check)."""
        avg = results['avg_newton_iterations']
        assert avg >= 1.0, (
            f"Average solver iterations {avg:.1f} < 1 — suspicious"
        )


class TestPhysicalPlausibility:
    """Test that results are physically plausible."""

    def test_link_positions_bounded(self, trajectories):
        """Link positions should stay within reasonable bounds."""
        pos1 = trajectories['positions_link1']
        pos2 = trajectories['positions_link2']
        max_dist = max(np.max(np.linalg.norm(pos1, axis=1)),
                       np.max(np.linalg.norm(pos2, axis=1)))
        assert max_dist < 3.0, (
            f"Link positions extend to {max_dist:.2f}m from origin — unphysical"
        )

    def test_link_positions_nondegenerate(self, trajectories):
        """Links must actually move during the simulation."""
        pos1 = trajectories['positions_link1']
        pos2 = trajectories['positions_link2']
        range1 = np.max(pos1, axis=0) - np.min(pos1, axis=0)
        range2 = np.max(pos2, axis=0) - np.min(pos2, axis=0)
        assert np.max(range1) > 0.01, "Link 1 appears stationary"
        assert np.max(range2) > 0.01, "Link 2 appears stationary"

    def test_trajectory_length(self, trajectories):
        """Trajectory must cover the full 10 seconds."""
        times = trajectories['times']
        assert times[-1] >= 9.99, (
            f"Trajectory only covers {times[-1]:.2f}s, expected ~10s"
        )
