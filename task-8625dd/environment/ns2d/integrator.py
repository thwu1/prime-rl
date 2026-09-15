"""Time integration for the Navier-Stokes solver."""


def ssp_rk3_step(omega, dt, rhs_fn):
    """SSP-RK3 time integration step."""
    L1 = rhs_fn(omega)
    w1 = omega + dt * L1

    L2 = rhs_fn(w1)
    w2 = 0.75 * omega + 0.25 * (w1 + dt * L2)

    L3 = rhs_fn(w2)
    return 0.5 * omega + 0.5 * (w2 + dt * L3)
