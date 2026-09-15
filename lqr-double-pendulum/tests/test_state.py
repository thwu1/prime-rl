"""
Tests for pendulum system stabilization controller.
Verifies linearization, controllability, stability, and closed-loop performance.
"""

import numpy as np
import mujoco
import pytest
import os

MODEL_PATH = '/app/model.xml'
RESULTS_DIR = '/app/results'

# Initial perturbation
Q0_PERTURB = [0.0, 0.15, -0.1]


@pytest.fixture
def mj():
    model = mujoco.MjModel.from_xml_path(MODEL_PATH)
    data = mujoco.MjData(model)
    return model, data


def test_results_exist():
    """All required output files must be present."""
    required = ['A.csv', 'B.csv', 'K.csv', 'trajectory.csv',
                'controllability_rank.txt', 'closed_loop_eigenvalues.csv']
    for fname in required:
        path = os.path.join(RESULTS_DIR, fname)
        assert os.path.exists(path), f"Missing required output: {fname}"


def test_matrix_shapes():
    """A must be 6x6, B must have 6 elements, K must have 6 elements."""
    A = np.loadtxt(os.path.join(RESULTS_DIR, 'A.csv'), delimiter=',')
    B = np.loadtxt(os.path.join(RESULTS_DIR, 'B.csv'), delimiter=',')
    K = np.loadtxt(os.path.join(RESULTS_DIR, 'K.csv'), delimiter=',')

    assert A.shape == (6, 6), f"A shape {A.shape} != (6, 6)"
    assert B.flatten().shape == (6,), f"B should have 6 elements, got {B.flatten().shape}"
    assert K.flatten().shape == (6,), f"K should have 6 elements, got {K.flatten().shape}"


def test_linearization_matches_reference(mj):
    """A and B matrices must match MuJoCo's finite-difference linearization at the equilibrium."""
    model, data = mj
    mujoco.mj_resetData(model, data)
    mujoco.mj_forward(model, data)

    nstate = model.nq + model.nv
    A_ref = np.zeros((nstate, nstate))
    B_ref = np.zeros((nstate, model.nu))
    mujoco.mjd_transitionFD(model, data, 1e-6, 1, A_ref, B_ref, None, None)

    A = np.loadtxt(os.path.join(RESULTS_DIR, 'A.csv'), delimiter=',')
    B = np.loadtxt(os.path.join(RESULTS_DIR, 'B.csv'), delimiter=',')
    if B.ndim == 1:
        B = B.reshape(-1, 1)

    np.testing.assert_allclose(A, A_ref, atol=1e-3,
        err_msg="Linearized A matrix does not match reference")
    np.testing.assert_allclose(B, B_ref, atol=1e-3,
        err_msg="Linearized B matrix does not match reference")


def test_controllability():
    """The controllability rank must equal the state dimension (full rank)."""
    with open(os.path.join(RESULTS_DIR, 'controllability_rank.txt')) as f:
        rank = int(f.read().strip())
    assert rank == 6, f"Controllability rank {rank} != 6"


def test_closed_loop_eigenvalues_stable():
    """All closed-loop eigenvalues of (A - BK) must lie strictly inside the unit circle."""
    A = np.loadtxt(os.path.join(RESULTS_DIR, 'A.csv'), delimiter=',')
    B = np.loadtxt(os.path.join(RESULTS_DIR, 'B.csv'), delimiter=',')
    K = np.loadtxt(os.path.join(RESULTS_DIR, 'K.csv'), delimiter=',')

    if B.ndim == 1:
        B = B.reshape(-1, 1)
    if K.ndim == 1:
        K = K.reshape(1, -1)

    Acl = A - B @ K
    eigs = np.linalg.eigvals(Acl)
    mags = np.abs(eigs)

    assert np.all(mags < 1.0), \
        f"Closed-loop not stable: eigenvalue magnitudes = {mags}"
    assert np.max(mags) < 0.999, \
        f"Closed-loop marginally stable: max eigenvalue magnitude = {np.max(mags):.6f}"


def test_controller_stabilizes(mj):
    """Run the submitted K matrix in a fresh simulation; system must stabilize."""
    model, data = mj
    K = np.loadtxt(os.path.join(RESULTS_DIR, 'K.csv'), delimiter=',')
    if K.ndim == 1:
        K = K.reshape(1, -1)

    mujoco.mj_resetData(model, data)
    data.qpos[:] = Q0_PERTURB
    data.qvel[:] = 0.0

    T = 10.0
    max_cart = 0.0
    max_ctrl = 0.0

    while data.time < T:
        x = np.concatenate([data.qpos.copy(), data.qvel.copy()])
        u = (-K @ x).flatten()
        u_clipped = np.clip(u, -100.0, 100.0)
        data.ctrl[:] = u_clipped

        max_cart = max(max_cart, abs(data.qpos[0]))
        max_ctrl = max(max_ctrl, abs(u_clipped[0]))

        mujoco.mj_step(model, data)

    # After 10 seconds, angles must be near zero
    assert abs(data.qpos[1]) < 0.02, \
        f"angle1 not stabilized at t=10s: {data.qpos[1]:.6f}"
    assert abs(data.qpos[2]) < 0.02, \
        f"angle2 not stabilized at t=10s: {data.qpos[2]:.6f}"
    assert max_cart < 2.0, \
        f"Cart exceeded +/-2m limit: max={max_cart:.3f}"
    assert max_ctrl <= 100.0 + 1e-6, \
        f"Control exceeded +/-100N limit: max={max_ctrl:.3f}"


def test_settles_within_5s(mj):
    """After t=5s, angles must remain below 0.01 rad and velocities below 0.1 rad/s."""
    model, data = mj
    K = np.loadtxt(os.path.join(RESULTS_DIR, 'K.csv'), delimiter=',')
    if K.ndim == 1:
        K = K.reshape(1, -1)

    mujoco.mj_resetData(model, data)
    data.qpos[:] = Q0_PERTURB
    data.qvel[:] = 0.0

    max_angle_after_5s = 0.0
    max_vel_after_5s = 0.0

    while data.time < 10.0:
        x = np.concatenate([data.qpos.copy(), data.qvel.copy()])
        u = (-K @ x).flatten()
        u_clipped = np.clip(u, -100.0, 100.0)
        data.ctrl[:] = u_clipped

        if data.time >= 5.0:
            angle_max = max(abs(data.qpos[1]), abs(data.qpos[2]))
            vel_max = max(abs(data.qvel[1]), abs(data.qvel[2]))
            max_angle_after_5s = max(max_angle_after_5s, angle_max)
            max_vel_after_5s = max(max_vel_after_5s, vel_max)

        mujoco.mj_step(model, data)

    assert max_angle_after_5s < 0.01, \
        f"Angles not settled after 5s: max_angle={max_angle_after_5s:.6f} rad"
    assert max_vel_after_5s < 0.1, \
        f"Velocities not settled after 5s: max_vel={max_vel_after_5s:.6f} rad/s"


def _load_trajectory():
    """Load trajectory CSV robustly, handling various header formats."""
    path = os.path.join(RESULTS_DIR, 'trajectory.csv')
    try:
        traj = np.loadtxt(path, delimiter=',')
    except ValueError:
        # Header line without '#' prefix -- skip it
        traj = np.loadtxt(path, delimiter=',', skiprows=1)
    return traj


def test_trajectory_format():
    """Trajectory CSV must have 8 columns and run for at least 9.9 seconds."""
    traj = _load_trajectory()
    # Handle optional header row
    if traj.ndim == 1:
        pytest.fail("Trajectory has only one row")
    assert traj.shape[1] == 8, f"Expected 8 columns, got {traj.shape[1]}"
    assert traj[-1, 0] >= 9.9, \
        f"Simulation too short: final time={traj[-1, 0]:.2f}s (need >= 9.9s)"
    assert traj.shape[0] >= 100, \
        f"Too few data points: {traj.shape[0]} (need >= 100)"
