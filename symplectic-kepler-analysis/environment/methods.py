"""
Time integration methods for separable Hamiltonian systems H = T(p) + V(q).

All step functions have signature:
    step_fn(q, p, dt, force_fn) -> (q_new, p_new)

where q, p are numpy arrays (position and momentum), dt is the time step,
and force_fn(q) returns the force F(q) = -dV/dq.

Methods A-E span different accuracy classes and structure-preserving
properties for benchmarking comparison.
"""
import numpy as np


def method_a(q, p, dt, force_fn):
    """First-order explicit method."""
    q_new = q + dt * p
    p_new = p + dt * force_fn(q)
    return q_new, p_new


def method_b(q, p, dt, force_fn):
    """Second-order symplectic splitting (kick-drift-kick)."""
    p_half = p + 0.5 * dt * force_fn(q)
    q_new = q + dt * p_half
    p_new = p_half + 0.5 * dt * force_fn(q)
    return q_new, p_new


def method_c(q, p, dt, force_fn):
    """Fourth-order explicit Runge-Kutta."""
    dq1 = p.copy()
    dp1 = force_fn(q)
    dq2 = p + 0.5 * dt * dp1
    dp2 = force_fn(q + 0.5 * dt * dq1)
    dq3 = p + 0.5 * dt * dp2
    dp3 = force_fn(q + 0.5 * dt * dq2)
    dq4 = p + dt * dp3
    dp4 = force_fn(q + dt * dq3)
    q_new = q + (dt / 6.0) * (dq1 + 2 * dq2 + 2 * dq3 + dq4)
    p_new = p + (dt / 6.0) * (dp1 + 2 * dp2 + 2 * dp3 + dp4)
    return q_new, p_new


def method_e(q, p, dt, force_fn):
    """Second-order symplectic splitting (drift-kick-drift)."""
    q_half = q + 0.5 * dt * p
    p_new = p + dt * force_fn(q_half)
    q_new = q_half + 0.5 * dt * p_new
    return q_new, p_new


def compose_method(base_fn, base_order):
    """Symmetric triple-stage composition to raise method order by 2.

    Given a symmetric integrator of even order 2k, produces a method of
    order 2k+2 through a three-stage composition with computed weights.
    """
    k = base_order // 2
    c = 2.0 ** (1.0 / (2 * k + 1))
    w1 = 1.0 / (2.0 + c)
    w0 = 1.0 - 2.0 * w1

    def composed(q, p, dt, force_fn):
        q, p = base_fn(q, p, w1 * dt, force_fn)
        q, p = base_fn(q, p, w0 * dt, force_fn)
        q, p = base_fn(q, p, w1 * dt, force_fn)
        return q, p

    return composed


method_d = compose_method(method_e, 2)


def integrate(step_fn, q0, p0, dt, num_steps, force_fn):
    """Integrate and record full phase-space trajectory.

    Returns:
        qs: array of shape (num_steps + 1, dim)
        ps: array of shape (num_steps + 1, dim)
    """
    dim = q0.shape[0]
    qs = np.empty((num_steps + 1, dim))
    ps = np.empty((num_steps + 1, dim))
    qs[0] = q0.copy()
    ps[0] = p0.copy()
    q, p = q0.copy(), p0.copy()
    for i in range(num_steps):
        q, p = step_fn(q, p, dt, force_fn)
        qs[i + 1] = q
        ps[i + 1] = p
    return qs, ps
