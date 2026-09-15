"""PFR and CSTR design equation solvers."""
import math


def solve_pfr(k, order, ca_in, v0, volume, epsilon_a):
    """Solve PFR design equation. Returns exit concentration.

    Parameters
    ----------
    k : float — rate constant
    order : int — reaction order (1 or 2)
    ca_in : float — inlet concentration
    v0 : float — volumetric flow rate
    volume : float — reactor volume
    epsilon_a : float — fractional volume change on complete conversion
    """
    tau = volume / v0
    if order == 1:
        return ca_in * math.exp(-k * tau)
    elif order == 2:
        return ca_in / (1.0 + k * ca_in * tau)
    else:
        raise ValueError(f"Order {order} not supported")


def solve_cstr(k, order, ca_in, v0, volume, epsilon_a):
    """Solve CSTR design equation. Returns exit concentration.

    Parameters
    ----------
    k : float — rate constant
    order : int — reaction order (1 or 2)
    ca_in : float — inlet concentration
    v0 : float — volumetric flow rate
    volume : float — reactor volume
    epsilon_a : float — fractional volume change on complete conversion
    """
    tau = volume / v0
    if order == 1:
        return ca_in / (1.0 + k * tau)
    elif order == 2:
        a = k * tau
        b = 1.0
        c = -ca_in
        disc = b * b - 4.0 * a * c
        return (-b + math.sqrt(disc)) / (2.0 * a)
    else:
        raise ValueError(f"Order {order} not supported")
