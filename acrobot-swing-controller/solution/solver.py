#!/usr/bin/env python3

"""
Acrobot swing-up controller using energy-based swing-up + LQR stabilization.

Strategy:
  1. Initial kick (0.05s) to escape the stable hanging equilibrium
  2. Energy pumping: u2 = -ke * (E - E_desired) * qdot2
     This drives the total energy toward E_desired (energy at upright)
  3. LQR stabilization when the state is near the upright equilibrium
     (triggered by cost-to-go threshold)
"""

import numpy as np
import json
import csv
from scipy.linalg import solve_continuous_are

# ---------- Load parameters ----------
with open("/app/params.json") as f:
    P = json.load(f)

m1, m2 = P["m1"], P["m2"]
l1, l2 = P["l1"], P["l2"]
r1, r2 = P["r1"], P["r2"]
I1, I2 = P["I1"], P["I2"]
b1, b2 = P["b1"], P["b2"]
cf1, cf2 = P["cf1"], P["cf2"]
Ir = P["Ir"]
gr_val = P["gr"]
g_acc = P["g"]
tau_max = P["torque_limit"][1]

B_act = np.array([[0.0, 0.0], [0.0, 1.0]])
x_goal = np.array([np.pi, 0.0, 0.0, 0.0])


# ---------- Dynamics ----------

def mass_matrix(q1, q2):
    c2 = np.cos(q2)
    M11 = I1 + I2 + m2 * l1**2 + 2 * m2 * l1 * r2 * c2 + gr_val**2 * Ir + Ir
    M12 = I2 + m2 * l1 * r2 * c2 - gr_val * Ir
    M22 = I2 + gr_val**2 * Ir
    return np.array([[M11, M12], [M12, M22]])


def coriolis_matrix(q1, q2, qd1, qd2):
    s2 = np.sin(q2)
    h = m2 * l1 * r2 * s2
    return np.array([[-2 * h * qd2, -h * qd2],
                     [h * qd1, 0.0]])


def gravity_vector(q1, q2):
    s1 = np.sin(q1)
    s12 = np.sin(q1 + q2)
    G1 = -m1 * g_acc * r1 * s1 - m2 * g_acc * (l1 * s1 + r2 * s12)
    G2 = -m2 * g_acc * r2 * s12
    return np.array([G1, G2])


def friction_vector(qd1, qd2):
    F1 = b1 * qd1 + cf1 * np.arctan(100 * qd1)
    F2 = b2 * qd2 + cf2 * np.arctan(100 * qd2)
    return np.array([F1, F2])


def forward_dynamics(x, u):
    q1, q2, qd1, qd2 = x
    M = mass_matrix(q1, q2)
    C = coriolis_matrix(q1, q2, qd1, qd2)
    G = gravity_vector(q1, q2)
    F = friction_vector(qd1, qd2)
    qd = np.array([qd1, qd2])
    Minv = np.linalg.inv(M)
    return Minv @ (B_act @ u - C @ qd + G - F)


def rhs_func(t, x, u):
    qdd = forward_dynamics(x, u)
    return np.array([x[2], x[3], qdd[0], qdd[1]])


def rk4_step(t, x, u, dt):
    k1 = rhs_func(t, x, u)
    k2 = rhs_func(t + 0.5 * dt, x + 0.5 * dt * k1, u)
    k3 = rhs_func(t + 0.5 * dt, x + 0.5 * dt * k2, u)
    k4 = rhs_func(t + dt, x + dt * k3, u)
    return x + (dt / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)


# ---------- Energy ----------

def total_energy(x):
    q1, q2, qd1, qd2 = x
    M = mass_matrix(q1, q2)
    qd = np.array([qd1, qd2])
    Ekin = 0.5 * qd @ M @ qd
    Epot = -m1 * g_acc * r1 * np.cos(q1) - m2 * g_acc * (l1 * np.cos(q1) + r2 * np.cos(q1 + q2))
    return Ekin + Epot


E_desired = total_energy(x_goal)


def ee_y(q1, q2):
    return -l1 * np.cos(q1) - l2 * np.cos(q1 + q2)


def wrap_angle(a):
    return ((a + np.pi) % (2 * np.pi)) - np.pi


# ---------- LQR ----------

def compute_lqr():
    """Linearize dynamics at upright equilibrium and solve CARE for LQR."""
    q10, q20 = np.pi, 0.0
    c1 = np.cos(q10)
    c12 = np.cos(q10 + q20)

    # Jacobian of gravity vector w.r.t. q at equilibrium
    dGdq = np.array([
        [-m1 * g_acc * r1 * c1 - m2 * g_acc * (l1 * c1 + r2 * c12),
         -m2 * g_acc * r2 * c12],
        [-m2 * g_acc * r2 * c12,
         -m2 * g_acc * r2 * c12]
    ])

    M0 = mass_matrix(q10, q20)
    M0inv = np.linalg.inv(M0)

    # State-space matrices: xdot = A*dx + B*du
    A = np.zeros((4, 4))
    A[0, 2] = 1.0
    A[1, 3] = 1.0
    A[2:, :2] = M0inv @ dGdq
    # A[2:, 2:] = 0 because b1=b2=cf1=cf2=0 and C=0 at qdot=0

    # Input matrix for acrobot (only u2 column)
    B_lin = np.zeros((4, 1))
    B_lin[2:, 0] = (M0inv @ B_act)[:, 1]

    # LQR weights
    Q_lqr = np.diag([10.0, 10.0, 1.0, 1.0])
    R_lqr = np.array([[1.0]])

    # Solve continuous-time algebraic Riccati equation
    P_care = solve_continuous_are(A, B_lin, Q_lqr, R_lqr)
    K_gain = (np.linalg.inv(R_lqr) @ B_lin.T @ P_care)[0]  # shape (4,)

    return K_gain, P_care


# ---------- Simulation ----------

def main():
    dt = 0.002
    T_final = 10.0
    n_steps = int(T_final / dt)

    K_lqr, P_lqr = compute_lqr()
    ke = 10.0          # energy controller gain
    lqr_threshold = 30.0  # cost-to-go threshold for switching to LQR

    x = np.array([0.0, 0.0, 0.0, 0.0])
    t = 0.0
    trajectory = []

    for step in range(n_steps):
        # --- Controller ---
        x_err = x - x_goal
        x_err[0] = wrap_angle(x_err[0])
        x_err[1] = wrap_angle(x_err[1])
        ctg = float(x_err @ P_lqr @ x_err)

        if ctg < lqr_threshold:
            # Phase 3: LQR stabilization near upright
            u2 = float(-K_lqr @ x_err)
        elif t < 0.05:
            # Phase 1: Initial kick to escape stable equilibrium
            u2 = tau_max
        else:
            # Phase 2: Energy-based swing-up
            E = total_energy(x)
            E_err = E - E_desired
            u2 = -ke * E_err * x[3]  # -ke * (E - E_des) * qdot2

        u2 = float(np.clip(u2, -tau_max, tau_max))
        u = np.array([0.0, u2])

        # Record current state and control
        trajectory.append([t, x[0], x[1], x[2], x[3], u[0], u[1]])

        # Integrate
        x = rk4_step(t, x, u, dt)
        t += dt

    # Record final state (no control applied)
    trajectory.append([t, x[0], x[1], x[2], x[3], 0.0, 0.0])

    traj = np.array(trajectory)

    # ---------- Write trajectory CSV ----------
    with open("/app/trajectory.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time", "q1", "q2", "qd1", "qd2", "u1", "u2"])
        for row in traj:
            writer.writerow([f"{v:.10f}" for v in row])

    # ---------- Compute RealAI Score ----------
    score_data = compute_score(traj)
    with open("/app/score.json", "w") as f:
        json.dump(score_data, f, indent=2)

    print(f"Trajectory: {len(traj)} points, t=[{traj[0,0]:.3f}, {traj[-1,0]:.3f}]")
    print(f"Final state: q1={traj[-1,1]:.4f}, q2={traj[-1,2]:.4f}, "
          f"qd1={traj[-1,3]:.4f}, qd2={traj[-1,4]:.4f}")
    print(f"Final EE height: {ee_y(traj[-1,1], traj[-1,2]):.4f} m")
    print(f"RealAI Score: {score_data['score']}")
    print(f"Swing-up success: {score_data['success']}")
    if score_data['success']:
        print(f"Swing-up time: {score_data['swingup_time']:.2f} s")


def compute_score(traj):
    T = traj[:, 0]
    X = traj[:, 1:5]
    U = traj[:, 5:7]
    dt_val = float(T[1] - T[0])
    N = len(T)

    # End-effector heights
    ee_h = np.array([ee_y(x[0], x[1]) for x in X])
    threshold = 0.45
    above = ee_h >= threshold

    if not above[-1]:
        return {"success": 0, "swingup_time": -1.0,
                "energy": 0.0, "torque_cost": 0.0,
                "torque_smoothness": 0.0, "velocity_cost": 0.0, "score": 0.0}

    # Swingup time: last contiguous above-threshold block including end
    idx = len(above) - 1
    while idx > 0 and above[idx - 1]:
        idx -= 1
    swingup_time = float(T[idx])

    # Energy cost: integral |u^T qdot| dt
    energy_cost = 0.0
    for i in range(N - 1):
        power = abs(U[i, 0] * X[i, 2] + U[i, 1] * X[i, 3])
        energy_cost += power * dt_val

    # Torque cost: integral u^T u dt
    torque_cost = 0.0
    for i in range(N - 1):
        torque_cost += float(U[i] @ U[i]) * dt_val

    # Torque smoothness: std of du
    du = np.diff(U, axis=0)
    torque_smooth = float(np.std(du)) if len(du) > 0 else 0.0

    # Velocity cost: integral qdot^T qdot dt
    vel_cost = 0.0
    for i in range(N - 1):
        vel_cost += float(X[i, 2]**2 + X[i, 3]**2) * dt_val

    # Normalizations
    n_t, n_e, n_tau, n_s, n_v = 20.0, 60.0, 20.0, 0.1, 400.0

    score = 1.0 - 0.2 * (
        np.tanh(swingup_time / n_t) +
        np.tanh(energy_cost / n_e) +
        np.tanh(torque_cost / n_tau) +
        np.tanh(torque_smooth / n_s) +
        np.tanh(vel_cost / n_v)
    )

    return {
        "success": 1,
        "swingup_time": round(swingup_time, 4),
        "energy": round(energy_cost, 4),
        "torque_cost": round(torque_cost, 4),
        "torque_smoothness": round(torque_smooth, 4),
        "velocity_cost": round(vel_cost, 4),
        "score": round(float(score), 4)
    }


if __name__ == "__main__":
    main()
