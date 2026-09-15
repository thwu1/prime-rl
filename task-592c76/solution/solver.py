#!/usr/bin/env python3
"""
Solution: Complete hybrid stiff ODE solver with event detection,
forward sensitivity analysis, and sparse Jacobian computation.

"""
import numpy as np
import json
import os
from scipy.integrate import solve_ivp
from scipy.sparse import csc_matrix

# ============================================================
# System parameters
# ============================================================
K1_P1 = 0.04; K2 = 3.0e7; K3_P1 = 1.0e4
K1_P2 = 0.01; K3_P2 = 2.5e3
Q1_VAL = 800.0; Q2_VAL = 2.0e-4; U_VAL = 0.1; TC = 290.0; T_CRIT = 375.0
Y0_STATE = np.array([1.0, 0.0, 0.0, 300.0])


# ============================================================
# ODE right-hand sides
# ============================================================
def _rhs(y, k1, k2, k3):
    A, B, C, T = y
    r1 = k1 * A; r2 = k2 * B**2; r3 = k3 * B * C
    return np.array([
        -r1 + r3,
        r1 - r2 - r3,
        r2,
        Q1_VAL * r1 + Q2_VAL * r2 - U_VAL * (T - TC)
    ])

def rhs_phase1(t, y):
    return _rhs(y, K1_P1, K2, K3_P1)

def rhs_phase2(t, y):
    return _rhs(y, K1_P2, K2, K3_P2)


# ============================================================
# Analytical sparse Jacobian (CSC format, 10 nonzeros)
# ============================================================
def _jac_sparse(y, k1, k2, k3):
    A, B, C, T = y
    data = np.array([
        -k1, k1, Q1_VAL * k1,                                  # col 0
        k3 * C, -2 * k2 * B - k3 * C, 2 * k2 * B, Q2_VAL * 2 * k2 * B,  # col 1
        k3 * B, -k3 * B,                                        # col 2
        -U_VAL                                                   # col 3
    ])
    row_ind = np.array([0, 1, 3,  0, 1, 2, 3,  0, 1,  3])
    col_ptr = np.array([0, 3, 7, 9, 10])
    return csc_matrix((data, row_ind, col_ptr), shape=(4, 4))

def jac_phase1(t, y):
    return _jac_sparse(y, K1_P1, K2, K3_P1)

def jac_phase2(t, y):
    return _jac_sparse(y, K1_P2, K2, K3_P2)


# ============================================================
# Parameter Jacobian B = df/dp, p = [k1_phase1, Q1, U]
# ============================================================
def pjac_phase1(t, y):
    A, B, C, T = y
    return np.array([
        [-A,          0.0,           0.0],
        [ A,          0.0,           0.0],
        [ 0.0,        0.0,           0.0],
        [Q1_VAL * A,  K1_P1 * A,    -(T - TC)]
    ])

def pjac_phase2(t, y):
    A, B, C, T = y
    return np.array([
        [0.0,         0.0,           0.0],
        [0.0,         0.0,           0.0],
        [0.0,         0.0,           0.0],
        [0.0,         K1_P2 * A,    -(T - TC)]
    ])


# ============================================================
# Augmented system: 16 equations (4 state + 12 sensitivity)
# ============================================================
def make_augmented_rhs(rhs_fn, jac_fn, pjac_fn):
    def f_aug(t, Y):
        y = Y[:4]
        S = Y[4:].reshape(4, 3)
        dy = rhs_fn(t, y)
        J = jac_fn(t, y).toarray()
        B = pjac_fn(t, y)
        dS = J @ S + B
        return np.concatenate([dy, dS.ravel()])
    return f_aug

aug_rhs_p1 = make_augmented_rhs(rhs_phase1, jac_phase1, pjac_phase1)
aug_rhs_p2 = make_augmented_rhs(rhs_phase2, jac_phase2, pjac_phase2)


# ============================================================
# Event function: temperature crossing T_CRIT (rising)
# ============================================================
def event_T_crit(t, Y):
    return Y[3] - T_CRIT
event_T_crit.terminal = True
event_T_crit.direction = 1


# ============================================================
# Main simulation
# ============================================================
def simulate():
    Y0 = np.zeros(16)
    Y0[:4] = Y0_STATE

    # --- Phase 1 ---
    sol1 = solve_ivp(
        aug_rhs_p1, [0.0, 100.0], Y0,
        method='BDF', events=event_T_crit,
        rtol=1e-8, atol=1e-10, dense_output=True, max_step=0.5
    )

    assert len(sol1.t_events[0]) > 0, "Phase transition event not detected"
    t_event = float(sol1.t_events[0][0])
    Y_event = sol1.y_events[0][0].copy()
    y_event = Y_event[:4]
    S_minus = Y_event[4:].reshape(4, 3).copy()

    # --- Sensitivity jump condition ---
    # At a state-dependent event g(y)=0 where the vector field switches,
    # the sensitivity matrix has a jump:
    # S+ = S- - (f_pre - f_post) * (nabla_g . S-) / (nabla_g . f_pre)
    f_pre = rhs_phase1(t_event, y_event)
    f_post = rhs_phase2(t_event, y_event)
    nabla_g = np.array([0.0, 0.0, 0.0, 1.0])
    nabla_g_dot_S = nabla_g @ S_minus
    nabla_g_dot_f = nabla_g @ f_pre
    S_plus = S_minus - np.outer(f_pre - f_post, nabla_g_dot_S) / nabla_g_dot_f

    Y_event_corrected = Y_event.copy()
    Y_event_corrected[4:] = S_plus.ravel()

    # --- Phase 2 ---
    sol2 = solve_ivp(
        aug_rhs_p2, [t_event, 100.0], Y_event_corrected,
        method='BDF',
        rtol=1e-8, atol=1e-10, dense_output=True, max_step=0.5
    )

    # --- Evaluate trajectory at integer times ---
    t_eval = np.arange(0, 101, dtype=float)
    trajectory = np.zeros((101, 4))
    for i, t in enumerate(t_eval):
        if t <= t_event:
            trajectory[i] = sol1.sol(t)[:4]
        else:
            trajectory[i] = sol2.sol(t)[:4]

    final_state = sol2.y[:4, -1]
    final_sens = sol2.y[4:, -1].reshape(4, 3)

    # --- Write outputs ---
    os.makedirs('/app/results', exist_ok=True)

    with open('/app/results/trajectory.json', 'w') as f:
        json.dump({
            'times': t_eval.tolist(),
            'states': trajectory.tolist()
        }, f)

    with open('/app/results/events.json', 'w') as f:
        json.dump({
            'event_time': t_event,
            'state_at_event': y_event.tolist()
        }, f)

    with open('/app/results/sensitivity.json', 'w') as f:
        json.dump({
            'sensitivity_matrix': final_sens.tolist(),
            'final_state': final_state.tolist()
        }, f)

    test_point = np.array([0.5, 1e-5, 0.3, 340.0])
    J_test = jac_phase1(0, test_point).toarray()
    with open('/app/results/jacobian.json', 'w') as f:
        json.dump({
            'test_point': test_point.tolist(),
            'jacobian': J_test.tolist(),
            'nnz': 10
        }, f)


if __name__ == '__main__':
    simulate()
