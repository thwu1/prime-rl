#!/usr/bin/env python3
"""
Discrete-time LQR stabilization of the pendulum system at the upright equilibrium.
Uses MuJoCo's finite-difference linearization (mjd_transitionFD) and scipy's DARE solver.
"""

import mujoco
import numpy as np
from scipy.linalg import solve_discrete_are
import os


def main():
    model = mujoco.MjModel.from_xml_path('/app/model.xml')
    data = mujoco.MjData(model)

    nq = model.nq
    nv = model.nv
    nu = model.nu
    nstate = nq + nv

    # Set to upright equilibrium: qpos=0 (both poles vertical), qvel=0, ctrl=0
    mujoco.mj_resetData(model, data)
    mujoco.mj_forward(model, data)

    # Compute discrete-time linearization via centered finite differences
    A = np.zeros((nstate, nstate))
    B = np.zeros((nstate, nu))
    mujoco.mjd_transitionFD(model, data, 1e-6, 1, A, B, None, None)

    # Controllability: rank of [B, AB, A^2B, ..., A^(n-1)B] must equal nstate
    Ctrb = np.zeros((nstate, nstate * nu))
    Ak = np.eye(nstate)
    for i in range(nstate):
        Ctrb[:, i * nu:(i + 1) * nu] = Ak @ B
        Ak = A @ Ak
    rank = int(np.linalg.matrix_rank(Ctrb))

    # LQR weight matrices: penalize angles heavily, use aggressive control
    Q = np.diag([1.0, 100.0, 100.0, 0.1, 10.0, 10.0])
    R = np.array([[0.01]])

    # Solve Discrete Algebraic Riccati Equation
    P = solve_discrete_are(A, B, Q, R)
    K = np.linalg.solve(R + B.T @ P @ B, B.T @ P @ A)

    # Closed-loop eigenvalues
    Acl = A - B @ K
    eigs = np.linalg.eigvals(Acl)

    # Simulate from perturbed initial condition
    mujoco.mj_resetData(model, data)
    data.qpos[0] = 0.0
    data.qpos[1] = 0.15
    data.qpos[2] = -0.1
    data.qvel[:] = 0.0

    T = 10.0
    trajectory = []

    while data.time < T:
        x = np.concatenate([data.qpos.copy(), data.qvel.copy()])
        u = (-K @ x).flatten()
        u_clipped = np.clip(u, model.actuator_ctrlrange[0, 0],
                            model.actuator_ctrlrange[0, 1])
        data.ctrl[:] = u_clipped

        trajectory.append([
            data.time,
            data.qpos[0], data.qpos[1], data.qpos[2],
            data.qvel[0], data.qvel[1], data.qvel[2],
            u_clipped[0]
        ])

        mujoco.mj_step(model, data)

    trajectory = np.array(trajectory)

    # Save all results
    os.makedirs('/app/results', exist_ok=True)

    np.savetxt('/app/results/A.csv', A, delimiter=',')
    np.savetxt('/app/results/B.csv', B, delimiter=',')
    np.savetxt('/app/results/K.csv', K, delimiter=',')
    np.savetxt('/app/results/trajectory.csv', trajectory, delimiter=',')

    with open('/app/results/controllability_rank.txt', 'w') as f:
        f.write(str(rank))

    eig_data = np.column_stack([eigs.real, eigs.imag])
    np.savetxt('/app/results/closed_loop_eigenvalues.csv', eig_data, delimiter=',')


if __name__ == '__main__':
    main()
