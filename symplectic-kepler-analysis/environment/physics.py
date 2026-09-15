"""
Kepler two-body orbit problem in 2D.

Hamiltonian: H(q, p) = |p|^2 / 2 - 1 / |q|

Equations of motion (separable Hamiltonian H = T(p) + V(q)):
  dq/dt =  dH/dp = p
  dp/dt = -dH/dq = -q / |q|^3

For an orbit with eccentricity e, at perihelion:
  q_0 = (1-e, 0),  p_0 = (0, sqrt((1+e)/(1-e)))
  Semi-major axis: a = 1
  Orbital period: T = 2*pi
"""
import numpy as np


def force(q):
    """Gravitational force: F(q) = -dV/dq = -q/|q|^3."""
    r = np.sqrt(q[0]**2 + q[1]**2)
    return -q / (r * r * r)


def hamiltonian(q, p):
    """Total energy H = T + V = |p|^2/2 - 1/|q|."""
    return 0.5 * np.dot(p, p) - 1.0 / np.sqrt(np.dot(q, q))


def angular_momentum(q, p):
    """z-component of angular momentum L = q_1*p_2 - q_2*p_1."""
    return q[0] * p[1] - q[1] * p[0]


ECCENTRICITY = 0.6
Q0 = np.array([1.0 - ECCENTRICITY, 0.0])
P0 = np.array([0.0, np.sqrt((1.0 + ECCENTRICITY) / (1.0 - ECCENTRICITY))])
PERIOD = 2.0 * np.pi
H0 = hamiltonian(Q0, P0)
L0 = angular_momentum(Q0, P0)
