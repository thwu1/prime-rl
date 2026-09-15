#!/usr/bin/env python3
"""Quadrotor dynamics simulator.

Implements first-principles rigid body dynamics for a plus-configuration
quadrotor. Quaternion convention: scalar-last [x, y, z, w].

Loads physical parameters from /app/data/sim_params.json and geometric/inertial
parameters from /app/data/known_params.json.

Usage:
    python3 simulator.py [n_steps]

Runs forward simulation from recorded initial conditions and compares
against recorded flight data.
"""

import json
import sys

import numpy as np


def load_params():
    """Load all parameters from config files."""
    with open("/app/data/known_params.json") as f:
        known = json.load(f)
    with open("/app/data/sim_params.json") as f:
        sim = json.load(f)
    return {**known, **sim}


def quat_multiply(q1, q2):
    """Hamilton quaternion product, scalar-last [x, y, z, w]."""
    x1, y1, z1, w1 = q1
    x2, y2, z2, w2 = q2
    return np.array([
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
    ])


def quat_to_rotmat(q):
    """Convert quaternion to 3x3 rotation matrix.

    Input quaternion uses scalar-last convention [x, y, z, w].
    """
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def step(pos, vel, quat, omega, rpms, params):
    """Single forward Euler integration step."""
    mass = params["mass"]
    kf = params["kf"]
    kt = params["kt"]
    L = params["arm_length"]
    Ixx = params["Ixx"]
    Iyy = params["Iyy"]
    Izz = params["Izz"]
    g = params["g"]
    dt = 0.002  # 500 Hz

    rpm_sq = rpms ** 2
    f = kf * rpm_sq

    # Collective force and body-frame torques (plus configuration)
    F_total = np.sum(f)
    tau_x = L * (f[3] - f[1])
    tau_y = L * (f[0] - f[2])
    tau_z = kt * (-rpm_sq[0] + rpm_sq[1] - rpm_sq[2] + rpm_sq[3])

    # Translational dynamics
    R = quat_to_rotmat(quat)
    acc = R @ np.array([0.0, 0.0, F_total]) / mass + np.array([0.0, 0.0, -g])

    # Rotational dynamics (Euler's rigid body equation)
    J_diag = np.array([Ixx, Iyy, Izz])
    tau = np.array([tau_x, tau_y, tau_z])
    ang_acc = (tau - np.cross(omega, J_diag * omega)) / J_diag

    # Quaternion derivative
    omega_q = np.array([omega[0], omega[1], omega[2], 0.0])
    q_dot = 0.5 * quat_multiply(quat, omega_q)

    # Forward Euler integration
    pos_new = pos + vel * dt
    vel_new = vel + acc * dt
    omega_new = omega + ang_acc * dt
    quat_new = quat + q_dot * dt
    quat_new = quat_new / np.linalg.norm(quat_new)

    return pos_new, vel_new, quat_new, omega_new


def main():
    n_steps = int(sys.argv[1]) if len(sys.argv) > 1 else 200

    params = load_params()
    data = np.load("/app/data/flight_data.npz")

    pos = data["positions"][0].copy()
    vel = data["velocities"][0].copy()
    quat = data["quaternions"][0].copy()
    omega = data["angular_velocities"][0].copy()

    print(f"Running {n_steps}-step forward simulation...")
    print(f"Parameters: mass={params['mass']}, kf={params['kf']:.3e}, kt={params['kt']:.3e}")
    print(f"Initial quaternion: {quat}")
    print()

    errors = []
    for t in range(min(n_steps, len(data["motor_rpms"]))):
        pos, vel, quat, omega = step(
            pos, vel, quat, omega, data["motor_rpms"][t], params
        )
        pos_err = np.linalg.norm(pos - data["positions"][t + 1])
        errors.append(pos_err)
        if t < 10 or t % 50 == 0:
            print(
                f"  t={t:4d} | pos_err={pos_err:.6e} m "
                f"| sim_z={pos[2]:.4f} | true_z={data['positions'][t + 1, 2]:.4f}"
            )

    print(f"\nMean position error: {np.mean(errors):.6e} m")
    print(f"Max position error:  {np.max(errors):.6e} m")
    print(f"Final position error: {errors[-1]:.6e} m")


if __name__ == "__main__":
    main()
