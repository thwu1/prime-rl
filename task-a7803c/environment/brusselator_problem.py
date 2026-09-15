"""
2D Brusselator Reaction-Diffusion System
=========================================

System of PDEs:
  dU/dt = (alpha/dx^2) * Lap(U) + B + U^2*V - (A+1)*U + f(x,y,t)
  dV/dt = (alpha/dx^2) * Lap(V) + A*U - U^2*V

Parameters:
  A = 3.4, B = 1.0, alpha = 10.0

Domain: [0,1] x [0,1], N=32 grid points per dimension
Boundary conditions: Neumann (zero-flux), implemented via edge replication
Source term: f(x,y,t) = 5.0 if t >= 1.1 and (x-0.3)^2 + (y-0.6)^2 <= 0.01
             f(x,y,t) = 0.0 otherwise

Initial conditions:
  U(x,y,0) = 22 * (y*(1-y))^(3/2)
  V(x,y,0) = 27 * (x*(1-x))^(3/2)

State vector layout (block ordering):
  y[0 : N*N]      = U field flattened in row-major (C) order
  y[N*N : 2*N*N]  = V field flattened in row-major (C) order

For grid point (i,j): U flat index = i*N + j
                      V flat index = N*N + i*N + j
"""

import numpy as np

N = 32
A_PARAM = 3.4
B_PARAM = 1.0
ALPHA = 10.0
T_SPAN = (0.0, 11.5)

xgrid = np.linspace(0, 1, N)
dx = xgrid[1] - xgrid[0]
D = ALPHA / dx**2

X, Y = np.meshgrid(xgrid, xgrid, indexing='ij')


def initial_conditions():
    """Return initial state vector y0 of length 2*N*N."""
    U0 = 22.0 * (Y * (1.0 - Y)) ** 1.5
    V0 = 27.0 * (X * (1.0 - X)) ** 1.5
    return np.concatenate([U0.ravel(), V0.ravel()])


def brusselator_rhs(t, y):
    """Right-hand side of the Brusselator ODE system."""
    NN = N * N
    U = y[:NN].reshape(N, N)
    V = y[NN:].reshape(N, N)

    U_pad = np.pad(U, 1, mode='edge')
    V_pad = np.pad(V, 1, mode='edge')

    lap_U = (U_pad[:-2, 1:-1] + U_pad[2:, 1:-1] +
             U_pad[1:-1, :-2] + U_pad[1:-1, 2:] - 4.0 * U)
    lap_V = (V_pad[:-2, 1:-1] + V_pad[2:, 1:-1] +
             V_pad[1:-1, :-2] + V_pad[1:-1, 2:] - 4.0 * V)

    source = np.zeros((N, N))
    if t >= 1.1:
        mask = (X - 0.3)**2 + (Y - 0.6)**2 <= 0.01
        source[mask] = 5.0

    dU = D * lap_U + B_PARAM + U**2 * V - (A_PARAM + 1.0) * U + source
    dV = D * lap_V + A_PARAM * U - U**2 * V

    return np.concatenate([dU.ravel(), dV.ravel()])


if __name__ == '__main__':
    from scipy.integrate import solve_ivp
    import time

    y0 = initial_conditions()
    print(f"System size: {len(y0)} unknowns")
    print(f"Diffusion coefficient D = alpha/dx^2 = {D:.1f}")
    print()
    print("Attempting short integration with RK45 (explicit, non-stiff)...")
    t0 = time.time()
    sol = solve_ivp(brusselator_rhs, (0.0, 0.1), y0, method='RK45',
                    rtol=1e-3, atol=1e-6)
    elapsed = time.time() - t0
    print(f"  t=[0, 0.1]: {elapsed:.1f}s, {sol.nfev} function evaluations")
    print(f"  Full integration to t=11.5 would require ~{sol.nfev * 115:.0f} evaluations")
    print()
    print("This system is stiff. An appropriate stiff solver with")
    print("sparse Jacobian information is required for efficiency.")
