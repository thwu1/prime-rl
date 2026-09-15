"""
Numerical integrators for Hamiltonian systems of the form H = T(p) + V(q).

All step functions have the signature:
    step_fn(q, p, dt, force_fn) -> (q_new, p_new)

where q and p are numpy arrays (position and momentum), dt is the time step,
and force_fn(q) returns the force F(q) = -dV/dq.

Implement the missing integrators:
1. Störmer-Verlet (leapfrog) symplectic integrator -- 2nd order
2. Yoshida symmetric composition -- raises order by 2
3. Integration loop that records full phase-space trajectories

Reference: H. Yoshida, "Construction of higher order symplectic integrators",
Physics Letters A, 150(5-7):262-268, 1990.
"""
import numpy as np


def rk4_step(q, p, dt, force_fn):
    """Classical 4th-order Runge-Kutta (non-symplectic).

    Applied to the separable system q'=p, p'=F(q).
    """
    dq1 = p.copy()
    dp1 = force_fn(q)
    dq2 = p + 0.5 * dt * dp1
    dp2 = force_fn(q + 0.5 * dt * dq1)
    dq3 = p + 0.5 * dt * dp2
    dp3 = force_fn(q + 0.5 * dt * dq2)
    dq4 = p + dt * dp3
    dp4 = force_fn(q + dt * dq3)
    q_new = q + (dt / 6.0) * (dq1 + 2.0 * dq2 + 2.0 * dq3 + dq4)
    p_new = p + (dt / 6.0) * (dp1 + 2.0 * dp2 + 2.0 * dp3 + dp4)
    return q_new, p_new


def verlet_step(q, p, dt, force_fn):
    """
    Störmer-Verlet (leapfrog) symplectic integrator -- 2nd order.

    This is a symplectic, time-reversible method using the kick-drift-kick form:
      1. Half-kick:  p_{1/2} = p_n     + (dt/2) * F(q_n)
      2. Full-drift: q_{n+1} = q_n     + dt     * p_{1/2}
      3. Half-kick:  p_{n+1} = p_{1/2} + (dt/2) * F(q_{n+1})

    Args:
        q: position array
        p: momentum array
        dt: time step size
        force_fn: callable, force_fn(q) -> F(q) = -dV/dq

    Returns:
        (q_new, p_new): updated position and momentum
    """
    raise NotImplementedError("Implement the Störmer-Verlet integrator")


def yoshida_compose(base_step_fn, base_order):
    """
    Yoshida (1990) symmetric triple-jump composition.

    Given a symmetric symplectic integrator S_{2k} of order 2k, constructs
    an integrator S_{2k+2} of order 2k+2 via the composition:

      S_{2k+2}(dt) = S_{2k}(w_1 * dt) o S_{2k}(w_0 * dt) o S_{2k}(w_1 * dt)

    The weights w_0 and w_1 are chosen so that all error terms of order 2k+1
    cancel in the symmetric composition, raising the method order by 2.
    Note that w_0 is negative -- the middle step integrates backward in time.
    This backward step is essential for the error cancellation.

    Args:
        base_step_fn: a function (q, p, dt, force_fn) -> (q_new, p_new)
                      that is symmetric and of order base_order
        base_order: the order of base_step_fn (must be a positive even integer)

    Returns:
        A new step function (q, p, dt, force_fn) -> (q_new, p_new)
        of order base_order + 2
    """
    raise NotImplementedError("Implement Yoshida composition")


def integrate(step_fn, q0, p0, dt, num_steps, force_fn):
    """
    Integrate a Hamiltonian system and record the full trajectory.

    Args:
        step_fn: step function with signature (q, p, dt, force_fn) -> (q_new, p_new)
        q0: initial position (numpy array of shape (dim,))
        p0: initial momentum (numpy array of shape (dim,))
        dt: time step
        num_steps: number of integration steps
        force_fn: force function, force_fn(q) -> F(q)

    Returns:
        qs: position trajectory, numpy array of shape (num_steps + 1, dim)
        ps: momentum trajectory, numpy array of shape (num_steps + 1, dim)
    """
    raise NotImplementedError("Implement the integration loop")
