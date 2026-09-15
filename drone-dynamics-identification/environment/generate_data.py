#!/usr/bin/env python3
"""Generate quadrotor flight trajectory data for system identification task.

This script simulates a Crazyflie-class quadrotor using first-principles dynamics
and saves trajectory data (positions, quaternions, commands, initial state) for
training and validation.
"""
import json
import os
import numpy as np

# Ground truth parameters (used only for data generation, NOT saved anywhere accessible)
_GT_PARAMS = {
    "Ixx": 1.395e-5,
    "Iyy": 1.436e-5,
    "Izz": 2.173e-5,
    "kf": 3.16e-10,
    "km": 7.94e-12,
    "drag": 0.01,
    "motor_tau": 30.0,
}

KNOWN_PARAMS = {
    "mass": 0.033,
    "L": 0.046,
    "g": 9.81,
}

DT = 0.002
N_STEPS_TRAIN = 750   # 1.5 s
N_STEPS_VAL = 500     # 1.0 s


def quat_multiply(q1, q2):
    x1, y1, z1, w1 = q1
    x2, y2, z2, w2 = q2
    return np.array([
        w1*x2 + x1*w2 + y1*z2 - z1*y2,
        w1*y2 - x1*z2 + y1*w2 + z1*x2,
        w1*z2 + x1*y2 - y1*x2 + z1*w2,
        w1*w2 - x1*x2 - y1*y2 - z1*z2,
    ])


def quat_rotate_vector(q, v):
    qv = np.array([v[0], v[1], v[2], 0.0])
    q_conj = np.array([-q[0], -q[1], -q[2], q[3]])
    return quat_multiply(quat_multiply(q, qv), q_conj)[:3]


def rotvec_to_quat(rv):
    angle = np.linalg.norm(rv)
    if angle < 1e-12:
        return np.array([0.0, 0.0, 0.0, 1.0])
    axis = rv / angle
    half = angle / 2.0
    s = np.sin(half)
    return np.array([axis[0]*s, axis[1]*s, axis[2]*s, np.cos(half)])


def normalize_quat(q):
    n = np.linalg.norm(q)
    return q / n if n > 1e-12 else np.array([0.0, 0.0, 0.0, 1.0])


def dynamics_step(pos, quat, vel, ang_vel, rotor_vel, cmd_rpm, p):
    mass = p["mass"]; L = p["L"]; g = p["g"]
    Ixx = p["Ixx"]; Iyy = p["Iyy"]; Izz = p["Izz"]
    kf = p["kf"]; km = p["km"]; drag = p["drag"]; motor_tau = p["motor_tau"]

    rotor_vel_new = rotor_vel + motor_tau * (cmd_rpm - rotor_vel) * DT
    w_sq = rotor_vel ** 2
    F_thrust = kf * np.sum(w_sq)
    a = L / np.sqrt(2.0)
    tau_x = kf * a * (-w_sq[0] - w_sq[1] + w_sq[2] + w_sq[3])
    tau_y = kf * a * (-w_sq[0] + w_sq[1] + w_sq[2] - w_sq[3])
    tau_z = km * (-w_sq[0] + w_sq[1] - w_sq[2] + w_sq[3])
    tau = np.array([tau_x, tau_y, tau_z])

    J = np.array([Ixx, Iyy, Izz])
    gyro = np.cross(ang_vel, J * ang_vel)
    ang_acc = (tau - gyro) / J

    thrust_world = quat_rotate_vector(quat, np.array([0.0, 0.0, F_thrust]))
    gravity = np.array([0.0, 0.0, -mass * g])
    drag_force = -drag * vel
    acc = (thrust_world + gravity + drag_force) / mass

    new_pos = pos + vel * DT
    new_vel = vel + acc * DT
    new_ang_vel = ang_vel + ang_acc * DT
    new_quat = normalize_quat(quat_multiply(quat, rotvec_to_quat(ang_vel * DT)))
    return new_pos, new_quat, new_vel, new_ang_vel, rotor_vel_new


def simulate(initial, commands, n_steps, params):
    pos = initial["pos"].copy()
    quat = initial["quat"].copy()
    vel = initial["vel"].copy()
    ang_vel = initial["ang_vel"].copy()
    rotor_vel = initial["rotor_vel"].copy()

    positions = np.zeros((n_steps, 3))
    quaternions = np.zeros((n_steps, 4))

    for i in range(n_steps):
        pos, quat, vel, ang_vel, rotor_vel = dynamics_step(
            pos, quat, vel, ang_vel, rotor_vel, commands[i], params
        )
        positions[i] = pos
        quaternions[i] = quat
    return positions, quaternions


def hover_rpm():
    m, g, kf = KNOWN_PARAMS["mass"], KNOWN_PARAMS["g"], _GT_PARAMS["kf"]
    return np.sqrt(m * g / (4 * kf))


def make_initial(pos=None):
    h = hover_rpm()
    return {
        "pos": np.array(pos if pos else [0.0, 0.0, 0.5]),
        "quat": np.array([0.0, 0.0, 0.0, 1.0]),
        "vel": np.zeros(3),
        "ang_vel": np.zeros(3),
        "rotor_vel": np.full(4, h),
    }


def save_trajectory(path, initial, commands, positions, quaternions):
    np.savez(
        path,
        times=np.arange(len(commands)) * DT,
        commands=commands,
        initial_pos=initial["pos"],
        initial_quat=initial["quat"],
        initial_vel=initial["vel"],
        initial_ang_vel=initial["ang_vel"],
        initial_rotor_vel=initial["rotor_vel"],
        positions=positions,
        quaternions=quaternions,
    )


# ---------- training trajectory generators ----------

def gen_thrust_ramp(n):
    h = hover_rpm()
    t = np.arange(n) * DT
    ramp = 0.90 + 0.30 * t / (n * DT)
    cmds = np.outer(ramp, np.ones(4)) * h
    return make_initial(), cmds


def gen_roll_excitation(n):
    h = hover_rpm()
    t = np.arange(n) * DT
    delta = 500 * np.sin(2 * np.pi * 2.0 * t)
    cmds = np.full((n, 4), h)
    cmds[:, 0] -= delta
    cmds[:, 1] -= delta
    cmds[:, 2] += delta
    cmds[:, 3] += delta
    return make_initial(), cmds


def gen_pitch_excitation(n):
    h = hover_rpm()
    t = np.arange(n) * DT
    delta = 450 * np.sin(2 * np.pi * 1.7 * t)
    cmds = np.full((n, 4), h)
    cmds[:, 0] -= delta
    cmds[:, 1] += delta
    cmds[:, 2] += delta
    cmds[:, 3] -= delta
    return make_initial(), cmds


def gen_yaw_excitation(n):
    h = hover_rpm()
    t = np.arange(n) * DT
    delta = 800 * np.sin(2 * np.pi * 1.2 * t)
    cmds = np.full((n, 4), h)
    cmds[:, 0] -= delta
    cmds[:, 1] += delta
    cmds[:, 2] -= delta
    cmds[:, 3] += delta
    return make_initial(), cmds


def gen_combined(n):
    h = hover_rpm()
    t = np.arange(n) * DT
    cmds = np.full((n, 4), h)
    cmds[:, 0] += 400*np.sin(2*np.pi*1.3*t) + 300*np.sin(2*np.pi*3.7*t)
    cmds[:, 1] += 350*np.sin(2*np.pi*2.1*t) + 250*np.sin(2*np.pi*5.3*t)
    cmds[:, 2] += 500*np.sin(2*np.pi*1.7*t+0.5) + 200*np.sin(2*np.pi*4.1*t)
    cmds[:, 3] += 380*np.sin(2*np.pi*2.9*t+1.0) + 320*np.sin(2*np.pi*6.1*t)
    return make_initial(), cmds


# ---------- validation trajectory generators ----------

def gen_val_mixed(n):
    h = hover_rpm()
    t = np.arange(n) * DT
    cmds = np.full((n, 4), h)
    roll_d = 300*np.sin(2*np.pi*2.5*t)
    pitch_d = 250*np.sin(2*np.pi*1.8*t)
    cmds[:, 0] += -roll_d - pitch_d
    cmds[:, 1] += -roll_d + pitch_d
    cmds[:, 2] += roll_d + pitch_d
    cmds[:, 3] += roll_d - pitch_d
    return make_initial([0.0, 0.0, 0.6]), cmds


def gen_val_yaw_step(n):
    h = hover_rpm()
    cmds = np.full((n, 4), h)
    step_start = int(0.2 / DT)
    cmds[step_start:, 0] -= 600
    cmds[step_start:, 1] += 600
    cmds[step_start:, 2] -= 600
    cmds[step_start:, 3] += 600
    return make_initial([0.0, 0.0, 0.7]), cmds


def gen_val_chirp(n):
    h = hover_rpm()
    t = np.arange(n) * DT
    freq = 1.0 + 5.0 * t / (n * DT)
    phase = 2 * np.pi * np.cumsum(freq) * DT
    d = 400 * np.sin(phase)
    cmds = np.full((n, 4), h)
    cmds[:, 0] += d
    cmds[:, 1] -= d * 0.7
    cmds[:, 2] += d * 0.5
    cmds[:, 3] -= d * 0.3
    return make_initial([0.0, 0.0, 0.8]), cmds


def main():
    all_params = {**KNOWN_PARAMS, **_GT_PARAMS}

    os.makedirs("/app/data/training", exist_ok=True)
    os.makedirs("/app/data/validation", exist_ok=True)

    train = {
        "thrust_ramp": gen_thrust_ramp,
        "roll_excitation": gen_roll_excitation,
        "pitch_excitation": gen_pitch_excitation,
        "yaw_excitation": gen_yaw_excitation,
        "combined": gen_combined,
    }
    for name, gen in train.items():
        init, cmds = gen(N_STEPS_TRAIN)
        pos, quat = simulate(init, cmds, N_STEPS_TRAIN, all_params)
        save_trajectory(f"/app/data/training/{name}.npz", init, cmds, pos, quat)
        print(f"  training/{name}.npz  pos range z=[{pos[:,2].min():.3f},{pos[:,2].max():.3f}]")

    val = {
        "val_mixed": gen_val_mixed,
        "val_yaw_step": gen_val_yaw_step,
        "val_chirp": gen_val_chirp,
    }
    for name, gen in val.items():
        init, cmds = gen(N_STEPS_VAL)
        pos, quat = simulate(init, cmds, N_STEPS_VAL, all_params)
        save_trajectory(f"/app/data/validation/{name}.npz", init, cmds, pos, quat)
        print(f"  validation/{name}.npz  pos range z=[{pos[:,2].min():.3f},{pos[:,2].max():.3f}]")

    print("Data generation complete.")


if __name__ == "__main__":
    main()
