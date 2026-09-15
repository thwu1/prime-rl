#!/usr/bin/env python3
"""Generate rigid-body trajectory datasets in HDF5 format for the physics
validation task.

Each scenario exercises a specific class of physical anomaly (or correctness).
Sphere trajectories use analytical solutions; ellipsoid tumbling uses RK4
integration of Euler's equations + quaternion kinematics.
"""

import math
import os
import random

import h5py

random.seed(42)
OUTPUT_DIR = "/app/data"


# ---------------------------------------------------------------------------
# quaternion helpers
# ---------------------------------------------------------------------------

def quat_mul(q1, q2):
    """Hamilton product of two quaternions [w, x, y, z]."""
    w1, x1, y1, z1 = q1
    w2, x2, y2, z2 = q2
    return [
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
    ]


def quat_norm(q):
    n = math.sqrt(sum(c * c for c in q))
    return [c / n for c in q]


def quat_to_rotmat(q):
    """Quaternion [w,x,y,z] → 3x3 rotation matrix (body→world)."""
    w, x, y, z = q
    return [
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
    ]


def mat_vec(M, v):
    return [sum(M[i][j] * v[j] for j in range(3)) for i in range(3)]


def quat_deriv(q, omega_body):
    """dq/dt = 0.5 * q ⊗ [0, ω_body]."""
    p = [0.0, omega_body[0], omega_body[1], omega_body[2]]
    qp = quat_mul(q, p)
    return [0.5 * c for c in qp]


# ---------------------------------------------------------------------------
# inertia helpers
# ---------------------------------------------------------------------------

def sphere_inertia_33(mass, radius):
    I = 0.4 * mass * radius * radius
    return [[I, 0, 0], [0, I, 0], [0, 0, I]]


def ellipsoid_inertia_33(mass, a, b, c):
    Ixx = mass / 5.0 * (b * b + c * c)
    Iyy = mass / 5.0 * (a * a + c * c)
    Izz = mass / 5.0 * (a * a + b * b)
    return [[Ixx, 0, 0], [0, Iyy, 0], [0, 0, Izz]]


# ---------------------------------------------------------------------------
# Euler equations integration (torque-free rigid body)
# ---------------------------------------------------------------------------

def euler_derivatives(omega, I_diag):
    I1, I2, I3 = I_diag
    w1, w2, w3 = omega
    return [
        (I2 - I3) * w2 * w3 / I1,
        (I3 - I1) * w3 * w1 / I2,
        (I1 - I2) * w1 * w2 / I3,
    ]


def integrate_tumble(I_diag, omega0, q0, dt, n_frames, sub_steps=20):
    """Integrate torque-free Euler equations + quaternion kinematics (RK4)."""
    dt_sub = dt / sub_steps
    omega = list(omega0)
    q = list(q0)

    omegas_world = []
    quaternions = []

    for _frame in range(n_frames):
        R = quat_to_rotmat(q)
        omegas_world.append(mat_vec(R, omega))
        quaternions.append(list(q))

        for _ in range(sub_steps):
            # RK4 for omega (Euler) and q (kinematics)
            dw1 = euler_derivatives(omega, I_diag)
            dq1 = quat_deriv(q, omega)

            w2 = [omega[i] + 0.5 * dt_sub * dw1[i] for i in range(3)]
            q2 = quat_norm([q[i] + 0.5 * dt_sub * dq1[i] for i in range(4)])
            dw2 = euler_derivatives(w2, I_diag)
            dq2 = quat_deriv(q2, w2)

            w3 = [omega[i] + 0.5 * dt_sub * dw2[i] for i in range(3)]
            q3 = quat_norm([q[i] + 0.5 * dt_sub * dq2[i] for i in range(4)])
            dw3 = euler_derivatives(w3, I_diag)
            dq3 = quat_deriv(q3, w3)

            w4 = [omega[i] + dt_sub * dw3[i] for i in range(3)]
            q4 = quat_norm([q[i] + dt_sub * dq3[i] for i in range(4)])
            dw4 = euler_derivatives(w4, I_diag)
            dq4 = quat_deriv(q4, w4)

            omega = [omega[i] + dt_sub / 6 * (dw1[i] + 2 * dw2[i] + 2 * dw3[i] + dw4[i])
                     for i in range(3)]
            q = quat_norm([q[i] + dt_sub / 6 * (dq1[i] + 2 * dq2[i] + 2 * dq3[i] + dq4[i])
                           for i in range(4)])

    return quaternions, omegas_world


# ---------------------------------------------------------------------------
# HDF5 writer
# ---------------------------------------------------------------------------

def write_hdf5(filepath, data):
    with h5py.File(filepath, "w") as f:
        f.attrs["dt"] = data["dt"]
        f.attrs["floor_z"] = data.get("floor_z", 0.0)
        f.create_dataset("gravity", data=data["gravity"])

        for body in data["bodies"]:
            g = f.create_group(body["name"])
            g.attrs["mass"] = float(body["mass"])
            g.attrs["shape_type"] = body["shape_type"]
            g.create_dataset("shape_params", data=body["shape_params"])
            g.create_dataset("inertia_tensor", data=body["inertia_tensor"])
            g.create_dataset("positions", data=body["positions"])
            g.create_dataset("quaternions", data=body["quaternions"])
            g.create_dataset("velocities", data=body["velocities"])
            g.create_dataset("angular_velocities", data=body["angular_velocities"])


# ---------------------------------------------------------------------------
# body constructors
# ---------------------------------------------------------------------------

def make_sphere(name, mass, radius, positions, velocities,
                quaternions=None, angular_velocities=None):
    n = len(positions)
    qid = [1.0, 0.0, 0.0, 0.0]
    return {
        "name": name, "mass": mass,
        "shape_type": "sphere", "shape_params": [radius],
        "inertia_tensor": sphere_inertia_33(mass, radius),
        "positions": positions,
        "quaternions": quaternions or [list(qid) for _ in range(n)],
        "velocities": velocities,
        "angular_velocities": angular_velocities or [[0.0, 0.0, 0.0] for _ in range(n)],
    }


def make_ellipsoid(name, mass, semi_axes, positions, velocities,
                   quaternions, angular_velocities):
    a, b, c = semi_axes
    return {
        "name": name, "mass": mass,
        "shape_type": "ellipsoid", "shape_params": list(semi_axes),
        "inertia_tensor": ellipsoid_inertia_33(mass, a, b, c),
        "positions": positions,
        "quaternions": quaternions,
        "velocities": velocities,
        "angular_velocities": angular_velocities,
    }


# ---------------------------------------------------------------------------
# bouncing ball (analytical)
# ---------------------------------------------------------------------------

def bouncing_ball(t, y0, radius, g, cor, gain_at_first_bounce=1.0):
    floor = radius
    h = y0 - floor
    v_impact = math.sqrt(2.0 * g * h)
    t_fall = v_impact / g

    if t <= t_fall:
        return y0 - 0.5 * g * t * t, -g * t

    t_rem = t - t_fall
    v_up = cor * gain_at_first_bounce * v_impact

    while v_up > 1e-10:
        t_phase = 2.0 * v_up / g
        if t_rem <= t_phase:
            return floor + v_up * t_rem - 0.5 * g * t_rem * t_rem, v_up - g * t_rem
        t_rem -= t_phase
        v_up *= cor

    return floor, 0.0


# ---------------------------------------------------------------------------
# scenario generators
# ---------------------------------------------------------------------------

def generate_correct_bounce():
    dt, g, radius, mass, cor = 0.01, 9.81, 0.5, 2.0, 0.8
    n = 400
    omega = [0.0, 0.0, 5.0]
    pos, vel = [], []
    for i in range(n):
        y, vy = bouncing_ball(i * dt, 5.0, radius, g, cor)
        pos.append([0.0, 0.0, y])
        vel.append([0.0, 0.0, vy])
    return {
        "dt": dt, "gravity": [0.0, 0.0, -g], "floor_z": 0.0,
        "bodies": [make_sphere("sphere", mass, radius, pos, vel,
                               angular_velocities=[list(omega) for _ in range(n)])],
    }


def generate_correct_collision():
    dt, n_frames, radius = 0.01, 200, 0.5
    m1, m2 = 2.0, 1.0
    v1, v2 = 3.0, -3.0
    cor = 0.8
    t_coll = 5.0 / 6.0
    xa_c = -3.0 + v1 * t_coll
    xb_c = 3.0 + v2 * t_coll
    v1p = ((m1 - cor * m2) * v1 + (1 + cor) * m2 * v2) / (m1 + m2)
    v2p = ((m2 - cor * m1) * v2 + (1 + cor) * m1 * v1) / (m1 + m2)
    omega_a = [3.0, 0.0, 0.0]
    omega_b = [0.0, 2.0, 0.0]
    pa, va, pb, vb = [], [], [], []
    for i in range(n_frames):
        t = i * dt
        if t <= t_coll:
            xa = -3.0 + v1 * t; xb = 3.0 + v2 * t
            vxa, vxb = v1, v2
        else:
            after = t - t_coll
            xa = xa_c + v1p * after; xb = xb_c + v2p * after
            vxa, vxb = v1p, v2p
        pa.append([xa, 0.0, 1.0]); va.append([vxa, 0.0, 0.0])
        pb.append([xb, 0.0, 1.0]); vb.append([vxb, 0.0, 0.0])
    return {
        "dt": dt, "gravity": [0.0, 0.0, 0.0], "floor_z": -100.0,
        "bodies": [
            make_sphere("sphere_a", m1, radius, pa, va,
                        angular_velocities=[list(omega_a) for _ in range(n_frames)]),
            make_sphere("sphere_b", m2, radius, pb, vb,
                        angular_velocities=[list(omega_b) for _ in range(n_frames)]),
        ],
    }


def generate_correct_tumble():
    """Torque-free asymmetric ellipsoid — angular momentum conserved in world frame."""
    dt = 0.005
    n_frames = 600
    mass = 5.0
    semi_axes = [2.0, 1.0, 0.5]
    I_mat = ellipsoid_inertia_33(mass, *semi_axes)
    I_diag = [I_mat[0][0], I_mat[1][1], I_mat[2][2]]  # [1.25, 4.25, 5.0]

    omega0_body = [5.0, 2.0, 1.0]
    q0 = [1.0, 0.0, 0.0, 0.0]

    quaternions, omegas_world = integrate_tumble(I_diag, omega0_body, q0, dt, n_frames)

    pos = [[0.0, 0.0, 5.0] for _ in range(n_frames)]
    vel = [[0.0, 0.0, 0.0] for _ in range(n_frames)]
    return {
        "dt": dt, "gravity": [0.0, 0.0, 0.0], "floor_z": -100.0,
        "bodies": [make_ellipsoid("ellipsoid", mass, semi_axes, pos, vel,
                                  quaternions, omegas_world)],
    }


def generate_energy_gain():
    dt, g, radius, mass, cor = 0.01, 9.81, 0.5, 2.0, 0.8
    n = 400
    pos, vel = [], []
    for i in range(n):
        y, vy = bouncing_ball(i * dt, 5.0, radius, g, cor, gain_at_first_bounce=1.3)
        pos.append([0.0, 0.0, y])
        vel.append([0.0, 0.0, vy])
    return {
        "dt": dt, "gravity": [0.0, 0.0, -g], "floor_z": 0.0,
        "bodies": [make_sphere("sphere", mass, radius, pos, vel)],
    }


def generate_interpenetration():
    dt, n_frames, radius, mass = 0.01, 200, 0.5, 1.0
    pa, va, pb, vb = [], [], [], []
    for i in range(n_frames):
        t = i * dt
        pa.append([-3.0 + 3.0 * t, 0.0, 1.0]); va.append([3.0, 0.0, 0.0])
        pb.append([3.0 - 3.0 * t, 0.0, 1.0]); vb.append([-3.0, 0.0, 0.0])
    return {
        "dt": dt, "gravity": [0.0, 0.0, 0.0], "floor_z": -100.0,
        "bodies": [
            make_sphere("sphere_a", mass, radius, pa, va),
            make_sphere("sphere_b", mass, radius, pb, vb),
        ],
    }


def generate_jittery_motion():
    dt, g, radius, mass = 0.01, 9.81, 0.5, 2.0
    n_frames, sigma = 300, 0.05
    pos, vel = [], []
    for i in range(n_frames):
        t = i * dt
        pos.append([0.0, 0.0, 50.0 - 0.5 * g * t * t + random.gauss(0.0, sigma)])
        vel.append([0.0, 0.0, -g * t])
    return {
        "dt": dt, "gravity": [0.0, 0.0, -g], "floor_z": 0.0,
        "bodies": [make_sphere("sphere", mass, radius, pos, vel)],
    }


def generate_momentum_violation():
    dt, n_frames, radius = 0.01, 200, 0.5
    m1, m2 = 2.0, 1.0
    v1, v2 = 3.0, -3.0
    t_coll = 5.0 / 6.0
    xa_c = -3.0 + v1 * t_coll
    xb_c = 3.0 + v2 * t_coll
    v1p_wrong, v2p_wrong = 1.0, 4.0
    pa, va, pb, vb = [], [], [], []
    for i in range(n_frames):
        t = i * dt
        if t <= t_coll:
            xa = -3.0 + v1 * t; xb = 3.0 + v2 * t
            vxa, vxb = v1, v2
        else:
            after = t - t_coll
            xa = xa_c + v1p_wrong * after; xb = xb_c + v2p_wrong * after
            vxa, vxb = v1p_wrong, v2p_wrong
        pa.append([xa, 0.0, 1.0]); va.append([vxa, 0.0, 0.0])
        pb.append([xb, 0.0, 1.0]); vb.append([vxb, 0.0, 0.0])
    return {
        "dt": dt, "gravity": [0.0, 0.0, 0.0], "floor_z": -100.0,
        "bodies": [
            make_sphere("sphere_a", m1, radius, pa, va),
            make_sphere("sphere_b", m2, radius, pb, vb),
        ],
    }


def generate_kinematic_mismatch():
    dt, n_frames, radius, mass, g = 0.01, 300, 0.5, 2.0, 9.81
    pos, vel = [], []
    for i in range(n_frames):
        t = i * dt
        pos.append([2.0 * t, 0.0, 20.0 - 0.5 * g * t * t])
        vel.append([2.5, 0.0, -g * t * 0.7])  # deliberately wrong
    return {
        "dt": dt, "gravity": [0.0, 0.0, -g], "floor_z": 0.0,
        "bodies": [make_sphere("sphere", mass, radius, pos, vel)],
    }


def generate_euler_drift():
    """Torque-free ellipsoid with decaying angular velocity — L_world NOT conserved."""
    dt = 0.005
    n_frames = 600
    mass = 5.0
    semi_axes = [2.0, 1.0, 0.5]
    omega0_body = [5.0, 2.0, 1.0]
    q = [1.0, 0.0, 0.0, 0.0]

    sub_steps = 20
    dt_sub = dt / sub_steps

    omegas_world = []
    quaternions = []

    for frame in range(n_frames):
        t = frame * dt
        # Body-frame angular velocity decays (violates Euler equations)
        omega_body = [omega0_body[k] * math.exp(-2.0 * t) for k in range(3)]

        R = quat_to_rotmat(q)
        omegas_world.append(mat_vec(R, omega_body))
        quaternions.append(list(q))

        # Integrate quaternion using RK4 with the decaying omega
        for s in range(sub_steps):
            t_s = t + s * dt_sub
            t_mid = t_s + 0.5 * dt_sub
            t_end = t_s + dt_sub
            w_s = [omega0_body[k] * math.exp(-2.0 * t_s) for k in range(3)]
            w_mid = [omega0_body[k] * math.exp(-2.0 * t_mid) for k in range(3)]
            w_end = [omega0_body[k] * math.exp(-2.0 * t_end) for k in range(3)]

            k1 = quat_deriv(q, w_s)
            q1 = quat_norm([q[i] + 0.5 * dt_sub * k1[i] for i in range(4)])
            k2 = quat_deriv(q1, w_mid)
            q2 = quat_norm([q[i] + 0.5 * dt_sub * k2[i] for i in range(4)])
            k3 = quat_deriv(q2, w_mid)
            q3 = quat_norm([q[i] + dt_sub * k3[i] for i in range(4)])
            k4 = quat_deriv(q3, w_end)
            q = quat_norm([q[i] + dt_sub / 6 * (k1[i] + 2 * k2[i] + 2 * k3[i] + k4[i])
                           for i in range(4)])

    pos = [[0.0, 0.0, 5.0] for _ in range(n_frames)]
    vel = [[0.0, 0.0, 0.0] for _ in range(n_frames)]
    return {
        "dt": dt, "gravity": [0.0, 0.0, 0.0], "floor_z": -100.0,
        "bodies": [make_ellipsoid("ellipsoid", mass, semi_axes, pos, vel,
                                  quaternions, omegas_world)],
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

SCENARIOS = {
    "correct_bounce": generate_correct_bounce,
    "correct_collision": generate_correct_collision,
    "correct_tumble": generate_correct_tumble,
    "energy_gain": generate_energy_gain,
    "interpenetration": generate_interpenetration,
    "jittery_motion": generate_jittery_motion,
    "momentum_violation": generate_momentum_violation,
    "kinematic_mismatch": generate_kinematic_mismatch,
    "euler_drift": generate_euler_drift,
}


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for name, fn in SCENARIOS.items():
        path = os.path.join(OUTPUT_DIR, f"{name}.h5")
        write_hdf5(path, fn())
        print(f"  wrote {path}")


if __name__ == "__main__":
    main()
