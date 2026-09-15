#!/usr/bin/env python3
"""
youBot Mobile Manipulation Simulation
Implements feedforward + PI task-space control for pick-and-place.
"""
import numpy as np
import modern_robotics as mr
import json
import os

# ── youBot kinematic parameters ──────────────────────────────────────────────
l = 0.235    # half forward-backward wheel distance
w = 0.15     # half side-to-side wheel distance
r = 0.0475   # wheel radius

Tb0 = np.array([[1, 0, 0, 0.1662],
                [0, 1, 0, 0],
                [0, 0, 1, 0.0026],
                [0, 0, 0, 1]])

M0e = np.array([[1, 0, 0, 0.033],
                [0, 1, 0, 0],
                [0, 0, 1, 0.6546],
                [0, 0, 0, 1]])

Blist = np.array([[0,  0, 1,       0, 0.033, 0],
                  [0, -1, 0, -0.5076,     0, 0],
                  [0, -1, 0, -0.3526,     0, 0],
                  [0, -1, 0, -0.2176,     0, 0],
                  [0,  0, 1,       0,     0, 0]]).T

# F: 3x4 matrix mapping wheel-angle changes to body displacement [dphi, dx, dy]
F = (r / 4.0) * np.array([
    [-1.0 / (l + w),  1.0 / (l + w),  1.0 / (l + w), -1.0 / (l + w)],
    [             1,              1,              1,              1],
    [            -1,              1,             -1,              1]
])

# F6: 6x4 embedding of F into spatial-velocity form [omg_x, omg_y, omg_z, v_x, v_y, v_z]
F6 = np.zeros((6, 4))
F6[2, :] = F[0, :]   # omega_z
F6[3, :] = F[1, :]   # v_x
F6[4, :] = F[2, :]   # v_y


# ── Core functions ───────────────────────────────────────────────────────────

def compute_end_effector_config(phi, x, y, theta_list):
    """Compute the end-effector SE(3) transform Tse from chassis and arm config."""
    Tsb = np.array([[np.cos(phi), -np.sin(phi), 0, x],
                    [np.sin(phi),  np.cos(phi), 0, y],
                    [0, 0, 1, 0.0963],
                    [0, 0, 0, 1]])
    T0e = mr.FKinBody(M0e, Blist, theta_list)
    return Tsb @ Tb0 @ T0e


def next_state(config, controls, dt, max_speed):
    """
    First-order Euler step for the full robot state.

    config:   12-vector [phi, x, y, J1..J5, W1..W4]
    controls: 9-vector  [u1..u4, dtheta1..dtheta5]
    """
    controls = np.clip(controls, -max_speed, max_speed)

    phi, x, y = config[0], config[1], config[2]
    theta = np.array(config[3:8])
    wheel = np.array(config[8:12])

    u      = controls[0:4]
    dtheta = controls[4:9]

    new_theta = theta + dtheta * dt
    new_wheel = wheel + u * dt

    # Mecanum-wheel odometry
    delta_wheel = u * dt
    dq = F @ delta_wheel     # [dphi_b, dx_b, dy_b]
    dphi_b = dq[0]
    dx_b   = dq[1]
    dy_b   = dq[2]

    if abs(dphi_b) < 1e-6:
        # Pure translation (first-order exact)
        new_phi = phi + dphi_b
        new_x = x + dx_b * np.cos(phi) - dy_b * np.sin(phi)
        new_y = y + dx_b * np.sin(phi) + dy_b * np.cos(phi)
    else:
        # SE(2) exact integration
        new_phi = phi + dphi_b
        dx_s = (dx_b * np.sin(dphi_b) + dy_b * (np.cos(dphi_b) - 1)) / dphi_b
        dy_s = (dy_b * np.sin(dphi_b) + dx_b * (1 - np.cos(dphi_b))) / dphi_b
        new_x = x + dx_s * np.cos(phi) - dy_s * np.sin(phi)
        new_y = y + dx_s * np.sin(phi) + dy_s * np.cos(phi)

    return np.array([new_phi, new_x, new_y,
                     *new_theta, *new_wheel])


def compute_mobile_jacobian(theta_list):
    """
    Compute the 6x9 mobile-manipulator Jacobian Je(theta) in the end-effector
    frame.  Columns 0-3 correspond to wheels, columns 4-8 to arm joints.
    """
    T0e = mr.FKinBody(M0e, Blist, theta_list)
    Teb = mr.TransInv(T0e) @ mr.TransInv(Tb0)
    Jbase = mr.Adjoint(Teb) @ F6
    Jarm  = mr.JacobianBody(Blist, theta_list)
    return np.hstack([Jbase, Jarm])


def feedback_control(X, Xd, Xd_next, Kp, Ki, dt, int_error):
    """
    Feedforward + PI task-space control.

    Returns (V, Xerr, new_int_error) where V is the commanded
    end-effector twist in the {e} frame.
    """
    Xerr = mr.se3ToVec(mr.MatrixLog6(mr.TransInv(X) @ Xd))
    new_int_error = int_error + Xerr * dt

    Vd = mr.se3ToVec((1.0 / dt) * mr.MatrixLog6(mr.TransInv(Xd) @ Xd_next))
    Ad = mr.Adjoint(mr.TransInv(X) @ Xd)

    V = Ad @ Vd + Kp @ Xerr + Ki @ new_int_error
    return V, Xerr, new_int_error


def compute_controls(V, theta_list, max_speed):
    """Map commanded twist V to wheel+joint speeds via Jacobian pseudo-inverse."""
    Je = compute_mobile_jacobian(theta_list)
    controls = np.linalg.pinv(Je, rcond=1e-2) @ V
    return np.clip(controls, -max_speed, max_speed)


# ── Trajectory generation ────────────────────────────────────────────────────

def generate_trajectory(Tse_init, Tsc_init, Tsc_goal,
                        Tce_grasp, Tce_standoff, dt=0.01):
    """
    Generate the 8-segment pick-and-place reference trajectory.
    Returns list of (Tse, gripper_state) tuples.
    """
    Tse_standoff_init = Tsc_init @ Tce_standoff
    Tse_grasp_init    = Tsc_init @ Tce_grasp
    Tse_standoff_goal = Tsc_goal @ Tce_standoff
    Tse_grasp_goal    = Tsc_goal @ Tce_grasp

    trajectory = []

    def _add_motion(Xstart, Xend, Tf, gripper, screw=True, skip_first=False):
        N = max(int(Tf / dt) + 1, 2)
        if screw:
            seg = mr.ScrewTrajectory(Xstart, Xend, Tf, N, 5)
        else:
            seg = mr.CartesianTrajectory(Xstart, Xend, Tf, N, 5)
        start = 1 if skip_first else 0
        for T in seg[start:]:
            trajectory.append((np.array(T), gripper))

    def _add_hold(T, gripper, Tf):
        N = max(int(Tf / dt), 1)
        for _ in range(N):
            trajectory.append((np.array(T), gripper))

    # Seg 1: move to standoff above initial cube
    _add_motion(Tse_init, Tse_standoff_init, 6.0, 0, screw=True)
    # Seg 2: lower to grasp
    _add_motion(Tse_standoff_init, Tse_grasp_init, 2.0, 0,
                screw=False, skip_first=True)
    # Seg 3: close gripper
    _add_hold(Tse_grasp_init, 1, 1.0)
    # Seg 4: raise to standoff
    _add_motion(Tse_grasp_init, Tse_standoff_init, 2.0, 1,
                screw=False, skip_first=True)
    # Seg 5: move to standoff above goal
    _add_motion(Tse_standoff_init, Tse_standoff_goal, 6.0, 1,
                screw=True, skip_first=True)
    # Seg 6: lower to place
    _add_motion(Tse_standoff_goal, Tse_grasp_goal, 2.0, 1,
                screw=False, skip_first=True)
    # Seg 7: open gripper
    _add_hold(Tse_grasp_goal, 0, 1.0)
    # Seg 8: raise to standoff
    _add_motion(Tse_grasp_goal, Tse_standoff_goal, 2.0, 0,
                screw=False, skip_first=True)

    return trajectory


# ── Main simulation ──────────────────────────────────────────────────────────

def main():
    with open('/app/config.json', 'r') as f:
        cfg = json.load(f)

    ci = cfg['cube_initial']
    cg = cfg['cube_goal']

    Tsc_init = np.array([
        [np.cos(ci['theta']), -np.sin(ci['theta']), 0, ci['x']],
        [np.sin(ci['theta']),  np.cos(ci['theta']), 0, ci['y']],
        [0, 0, 1, 0.025],
        [0, 0, 0, 1]
    ])
    Tsc_goal = np.array([
        [np.cos(cg['theta']), -np.sin(cg['theta']), 0, cg['x']],
        [np.sin(cg['theta']),  np.cos(cg['theta']), 0, cg['y']],
        [0, 0, 1, 0.025],
        [0, 0, 0, 1]
    ])

    Tse_init     = np.array(cfg['Tse_initial'],  dtype=float)
    Tce_grasp    = np.array(cfg['Tce_grasp'],    dtype=float)
    Tce_standoff = np.array(cfg['Tce_standoff'], dtype=float)

    Kp_mat = cfg['Kp'] * np.eye(6)
    Ki_mat = cfg['Ki'] * np.eye(6)
    dt        = cfg['dt']
    max_speed = cfg['max_speed']

    robot_initial = np.array(cfg['robot_initial'], dtype=float)

    # ── Generate reference trajectory ──
    print("Generating reference trajectory...")
    ref_traj = generate_trajectory(
        Tse_init, Tsc_init, Tsc_goal, Tce_grasp, Tce_standoff, dt
    )
    print(f"  {len(ref_traj)} reference configurations")

    # ── Run control loop ──
    current_config = robot_initial[:12].copy()
    int_error = np.zeros(6)

    traj_out = []
    err_out  = []

    print("Running simulation...")
    for i in range(len(ref_traj) - 1):
        Xd      = ref_traj[i][0]
        Xd_next = ref_traj[i + 1][0]
        gripper = ref_traj[i][1]

        X = compute_end_effector_config(
            current_config[0], current_config[1], current_config[2],
            current_config[3:8]
        )

        V, Xerr, int_error = feedback_control(
            X, Xd, Xd_next, Kp_mat, Ki_mat, dt, int_error
        )

        controls = compute_controls(V, current_config[3:8], max_speed)

        # Record state
        row = list(current_config[:3]) + list(current_config[3:8]) \
            + list(current_config[8:12]) + [gripper]
        traj_out.append(row)
        err_out.append(list(Xerr))

        # Integrate forward
        current_config = next_state(current_config, controls, dt, max_speed)

    # Final row
    gripper = ref_traj[-1][1]
    row = list(current_config[:3]) + list(current_config[3:8]) \
        + list(current_config[8:12]) + [gripper]
    traj_out.append(row)

    # ── Write output ──
    os.makedirs('/app/output', exist_ok=True)

    print("Writing trajectory.csv ...")
    with open('/app/output/trajectory.csv', 'w') as f:
        for row in traj_out:
            f.write(','.join(f'{v:.6f}' for v in row) + '\n')

    print("Writing error_log.csv ...")
    with open('/app/output/error_log.csv', 'w') as f:
        for row in err_out:
            f.write(','.join(f'{v:.6f}' for v in row) + '\n')

    final_err_norm = np.linalg.norm(err_out[-1])
    print(f"Final error magnitude: {final_err_norm:.6f}")
    print("Done.")


if __name__ == '__main__':
    main()
