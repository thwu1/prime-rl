"""System identification via nonlinear least squares — complete implementation."""

import numpy as np
from scipy.optimize import least_squares
from dynamics import compute_body_wrench, quat_to_rotation_matrix


def estimate_parameters(data_files, known_params):
    """Estimate mass, k_f, k_m from flight recordings using least-squares.

    Residuals are formed from the difference between observed accelerations
    (finite-differenced from state data) and model-predicted accelerations.
    """
    arm_length = known_params['arm_length']
    J = known_params['J']
    J_inv = known_params['J_inv']
    drag = known_params['drag']
    g = known_params['g']

    # Collect all observations across flights
    all_obs_acc = []      # observed translational acceleration
    all_obs_ang_acc = []   # observed angular acceleration
    all_quats = []
    all_vels = []
    all_ang_vels = []
    all_rpms = []

    for fpath in data_files:
        data = np.load(fpath)
        positions = data['positions']
        velocities = data['velocities']
        quaternions = data['quaternions']
        angular_velocities = data['angular_velocities']
        rotor_rpms = data['rotor_rpms']
        times = data['times']

        T = len(rotor_rpms)
        dt = times[1] - times[0]

        # Finite-difference accelerations (using velocity data for less noise)
        obs_acc = (velocities[1:] - velocities[:-1]) / dt         # (T, 3)
        obs_ang_acc = (angular_velocities[1:] - angular_velocities[:-1]) / dt  # (T, 3)

        # Use every 5th sample to reduce correlation and speed up optimization
        step = 5
        indices = np.arange(0, T, step)

        all_obs_acc.append(obs_acc[indices])
        all_obs_ang_acc.append(obs_ang_acc[indices])
        all_quats.append(quaternions[indices])
        all_vels.append(velocities[indices])
        all_ang_vels.append(angular_velocities[indices])
        all_rpms.append(rotor_rpms[indices])

    obs_acc = np.concatenate(all_obs_acc, axis=0)
    obs_ang_acc = np.concatenate(all_obs_ang_acc, axis=0)
    quats = np.concatenate(all_quats, axis=0)
    vels = np.concatenate(all_vels, axis=0)
    ang_vels = np.concatenate(all_ang_vels, axis=0)
    rpms = np.concatenate(all_rpms, axis=0)
    N = len(obs_acc)

    # Precompute RPM-squared terms
    rpm_sq = rpms ** 2
    d = arm_length / np.sqrt(2.0)

    # Precompute rotation matrices for all samples
    rot_matrices = np.array([quat_to_rotation_matrix(q) for q in quats])

    # Precompute gyroscopic cross product: cross(w, J @ w)
    Jw = np.array([J @ w for w in ang_vels])
    cross_wJw = np.cross(ang_vels, Jw)

    def residuals(x):
        mass, k_f, k_m = x

        # Thrust per motor
        thrusts = k_f * rpm_sq  # (N, 4)
        moments = k_m * rpm_sq  # (N, 4)

        # Body force: only z-component
        fz = np.sum(thrusts, axis=1)  # (N,)

        # Body torques
        tau_x = d * (thrusts[:, 0] + thrusts[:, 1] - thrusts[:, 2] - thrusts[:, 3])
        tau_y = d * (-thrusts[:, 0] + thrusts[:, 1] + thrusts[:, 2] - thrusts[:, 3])
        tau_z = moments[:, 0] - moments[:, 1] + moments[:, 2] - moments[:, 3]

        # World-frame thrust: R @ [0, 0, fz]^T = R[:, 2] * fz
        thrust_world = rot_matrices[:, :, 2] * fz[:, None]  # (N, 3)

        # Model acceleration: (thrust + gravity + drag) / mass
        gravity = np.array([0.0, 0.0, -mass * g])
        drag_force = -np.array([drag @ v for v in vels])  # (N, 3)
        model_acc = (thrust_world + gravity[None, :] + drag_force) / mass  # (N, 3)

        # Model angular acceleration: J_inv @ (tau - cross(w, Jw))
        tau = np.column_stack([tau_x, tau_y, tau_z])  # (N, 3)
        net_torque = tau - cross_wJw  # (N, 3)
        model_ang_acc = np.array([J_inv @ nt for nt in net_torque])  # (N, 3)

        # Residuals: [translational, angular] for all samples
        res_trans = (obs_acc - model_acc).ravel()
        res_ang = (obs_ang_acc - model_ang_acc).ravel()

        return np.concatenate([res_trans, res_ang])

    # Initial guesses computed from hover equilibrium and angular dynamics
    # Rough estimate: from roll flight angular acceleration, estimate k_f first
    k_f_init = 3.0e-10
    mass_init = 4 * k_f_init * np.mean(rpm_sq[quats.shape[0] // 4:quats.shape[0] // 2, :]) / g
    if mass_init < 0.01 or mass_init > 0.1:
        mass_init = 0.03
    k_m_init = k_f_init / 40.0

    x0 = np.array([mass_init, k_f_init, k_m_init])

    result = least_squares(
        residuals,
        x0,
        bounds=([0.005, 1e-12, 1e-14], [0.2, 1e-7, 1e-9]),
        method='trf',
        ftol=1e-12,
        xtol=1e-12,
        gtol=1e-12,
        max_nfev=500,
    )

    mass_est, k_f_est, k_m_est = result.x
    print(f"SysID converged: cost={result.cost:.2e}, nfev={result.nfev}")
    print(f"  mass={mass_est:.6f}, k_f={k_f_est:.4e}, k_m={k_m_est:.4e}")

    return {
        'mass': mass_est,
        'k_f': k_f_est,
        'k_m': k_m_est,
    }
