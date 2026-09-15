"""
Parameterized ODE systems for bifurcation analysis.

Each system in the SYSTEMS dictionary provides:
  - dim: state-space dimension
  - rhs(x, p): right-hand side f(x, p) returning ndarray of shape (dim,)
  - jacobian(x, p): Jacobian df/dx returning ndarray of shape (dim, dim)
  - param_name: name of the free parameter
  - param_range: (lo, hi) tuple bounding the continuation interval
  - initial_state: ndarray equilibrium at initial_param
  - initial_param: starting parameter value
"""

import numpy as np


# ---------------------------------------------------------------------------
# System 1: Cusp normal form (1D)
#   dx/dt = mu + x - x^3
# ---------------------------------------------------------------------------

def _cusp_rhs(x, mu):
    return np.array([mu + x[0] - x[0]**3])

def _cusp_jac(x, mu):
    return np.array([[1.0 - 3.0 * x[0]**2]])


# ---------------------------------------------------------------------------
# System 2: Brusselator (2D)
#   dx/dt = A - (B+1)*x + x^2*y
#   dy/dt = B*x - x^2*y
#   Fixed A = 1.5, free parameter B
# ---------------------------------------------------------------------------

_BRUS_A = 1.5

def _brusselator_rhs(x, B):
    A = _BRUS_A
    return np.array([
        A - (B + 1.0) * x[0] + x[0]**2 * x[1],
        B * x[0] - x[0]**2 * x[1],
    ])

def _brusselator_jac(x, B):
    return np.array([
        [-(B + 1.0) + 2.0 * x[0] * x[1], x[0]**2],
        [B - 2.0 * x[0] * x[1],          -x[0]**2],
    ])


# ---------------------------------------------------------------------------
# System 3: ABC Reaction (3D)
#   du1/dt = -u1 + p1*(1-u1)*exp(u3)
#   du2/dt = -u2 + p1*exp(u3)*(1-u1-p5*u2)
#   du3/dt = -u3 - p3*u3 + p1*p4*exp(u3)*(1-u1+p2*p5*u2)
#   Fixed: p2=1, p3=1.5, p4=8, p5=0.04
#   Free parameter: p1
# ---------------------------------------------------------------------------

_ABC_P2 = 1.0
_ABC_P3 = 1.5
_ABC_P4 = 8.0
_ABC_P5 = 0.04

def _abc_rhs(x, p1):
    u1, u2, u3 = x
    e = np.exp(u3)
    return np.array([
        -u1 + p1 * (1.0 - u1) * e,
        -u2 + p1 * e * (1.0 - u1 - _ABC_P5 * u2),
        -u3 - _ABC_P3 * u3 + p1 * _ABC_P4 * e * (1.0 - u1 + _ABC_P2 * _ABC_P5 * u2),
    ])

def _abc_jac(x, p1):
    u1, u2, u3 = x
    e = np.exp(u3)
    return np.array([
        [-1.0 - p1 * e,
         0.0,
         p1 * (1.0 - u1) * e],
        [-p1 * e,
         -1.0 - p1 * _ABC_P5 * e,
         p1 * e * (1.0 - u1 - _ABC_P5 * u2)],
        [-p1 * _ABC_P4 * e,
         p1 * _ABC_P4 * _ABC_P2 * _ABC_P5 * e,
         -(1.0 + _ABC_P3) + p1 * _ABC_P4 * e * (1.0 - u1 + _ABC_P2 * _ABC_P5 * u2)],
    ])


# ---------------------------------------------------------------------------

SYSTEMS = {
    "cusp_normal_form": {
        "dim": 1,
        "rhs": _cusp_rhs,
        "jacobian": _cusp_jac,
        "param_name": "mu",
        "param_range": (-1.0, 1.0),
        "initial_state": np.array([-1.32472]),
        "initial_param": -1.0,
    },
    "brusselator": {
        "dim": 2,
        "rhs": _brusselator_rhs,
        "jacobian": _brusselator_jac,
        "param_name": "B",
        "param_range": (0.5, 5.0),
        "initial_state": np.array([1.5, 1.0 / 3.0]),
        "initial_param": 0.5,
    },
    "abc_reaction": {
        "dim": 3,
        "rhs": _abc_rhs,
        "jacobian": _abc_jac,
        "param_name": "p1",
        "param_range": (0.05, 0.5),
        "initial_state": np.array([0.13305533, 0.13224348, 0.42837496]),
        "initial_param": 0.1,
    },
}
