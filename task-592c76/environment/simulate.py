#!/usr/bin/env python3
"""
Batch reactor simulation scaffold.

Integrates the Phase 1 ODE system to t=100 using scipy's BDF solver.
Event detection, phase switching, forward sensitivity analysis, and
sparse analytical Jacobian computation are NOT implemented.
All non-trajectory outputs are placeholders.
"""
import numpy as np
import json
import os
from scipy.integrate import solve_ivp


# ---- System parameters (from reactor.conf) ----
K1_P1 = 0.04;  K2 = 3e7;   K3_P1 = 1e4
K1_P2 = 0.01;              K3_P2 = 2.5e3
Q1 = 800.0;  Q2 = 2e-4;  U = 0.1;  TC = 290.0
T_CRIT = 375.0
Y0 = np.array([1.0, 0.0, 0.0, 300.0])

SENS_PARAMS = ['k1_phase1', 'Q1', 'U']


def rhs(y, k1, k2, k3):
    """ODE right-hand side for the batch reactor."""
    A, B, C, T = y
    r1, r2, r3 = k1*A, k2*B**2, k3*B*C
    return np.array([
        -r1 + r3,
         r1 - r2 - r3,
         r2,
         Q1*r1 + Q2*r2 - U*(T - TC)
    ])


rhs_p1 = lambda t, y: rhs(y, K1_P1, K2, K3_P1)
rhs_p2 = lambda t, y: rhs(y, K1_P2, K2, K3_P2)


def main():
    # --- Phase 1 only (no event detection, no phase switching) ---
    sol = solve_ivp(rhs_p1, [0, 100], Y0, method='BDF',
                    rtol=1e-8, atol=1e-10, max_step=0.5, dense_output=True)

    times = np.arange(0, 101, dtype=float)
    states = np.zeros((101, 4))
    for i, t in enumerate(times):
        states[i] = sol.sol(t)[:4]

    os.makedirs('/app/results', exist_ok=True)

    with open('/app/results/trajectory.json', 'w') as f:
        json.dump({'times': times.tolist(), 'states': states.tolist()}, f)

    # Placeholder outputs — not yet implemented
    with open('/app/results/events.json', 'w') as f:
        json.dump({'event_time': 0.0, 'state_at_event': [0, 0, 0, 0]}, f)

    with open('/app/results/sensitivity.json', 'w') as f:
        json.dump({'sensitivity_matrix': [[0]*3]*4, 'final_state': [0]*4}, f)

    with open('/app/results/jacobian.json', 'w') as f:
        json.dump({'test_point': [0.5, 1e-5, 0.3, 340.0],
                   'jacobian': [[0]*4]*4, 'nnz': 0}, f)


if __name__ == '__main__':
    main()
