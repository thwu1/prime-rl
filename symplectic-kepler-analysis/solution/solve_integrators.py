"""
Complete integrator implementations for the Kepler analysis task.

Implements:
  - Störmer-Verlet (leapfrog, kick-drift-kick) -- order 2
  - Yoshida symmetric triple-jump composition  -- order 2k -> 2k+2
  - Integration loop with trajectory recording
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

    Kick-drift-kick form:
      1. Half-kick:  p_{1/2} = p_n     + (dt/2) * F(q_n)
      2. Full-drift: q_{n+1} = q_n     + dt     * p_{1/2}
      3. Half-kick:  p_{n+1} = p_{1/2} + (dt/2) * F(q_{n+1})
    """
    # Half-kick: update momentum by half step using force at current position
    p_half = p + 0.5 * dt * force_fn(q)
    # Full-drift: update position using the half-updated momentum
    q_new = q + dt * p_half
    # Half-kick: update momentum by half step using force at new position
    p_new = p_half + 0.5 * dt * force_fn(q_new)
    return q_new, p_new


def yoshida_compose(base_step_fn, base_order):
    """
    Yoshida (1990) symmetric triple-jump composition.

    Given a symmetric symplectic integrator S_{2k} of order 2k, constructs
    S_{2k+2} of order 2k+2 via:

      S_{2k+2}(dt) = S_{2k}(w1*dt) o S_{2k}(w0*dt) o S_{2k}(w1*dt)

    where k = base_order // 2 and:
      w1 = 1 / (2 - 2^(1/(2k+1)))
      w0 = 1 - 2*w1

    Note: w0 < 0, so the middle step integrates backward in time.
    This negative step is essential for cancelling the leading error terms.
    """
    k = base_order // 2
    # Compute the composition weights from the order conditions
    c = 2.0 ** (1.0 / (2 * k + 1))
    w1 = 1.0 / (2.0 - c)
    w0 = 1.0 - 2.0 * w1   # This is negative: -(2^(1/(2k+1))) / (2 - 2^(1/(2k+1)))

    def composed_step(q, p, dt, force_fn):
        # Three-stage symmetric composition
        q, p = base_step_fn(q, p, w1 * dt, force_fn)
        q, p = base_step_fn(q, p, w0 * dt, force_fn)
        q, p = base_step_fn(q, p, w1 * dt, force_fn)
        return q, p

    return composed_step


def integrate(step_fn, q0, p0, dt, num_steps, force_fn):
    """
    Integrate a Hamiltonian system and record the full trajectory.

    Returns:
        qs: numpy array of shape (num_steps + 1, dim) -- positions
        ps: numpy array of shape (num_steps + 1, dim) -- momenta
    """
    dim = q0.shape[0]
    qs = np.empty((num_steps + 1, dim))
    ps = np.empty((num_steps + 1, dim))

    qs[0] = q0.copy()
    ps[0] = p0.copy()

    q = q0.copy()
    p = p0.copy()

    for i in range(num_steps):
        q, p = step_fn(q, p, dt, force_fn)
        qs[i + 1] = q
        ps[i + 1] = p

    return qs, ps
