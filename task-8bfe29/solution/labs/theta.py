"""Counterdiabatic optimization schedule parameters."""

from math import sin, pi

from labs.interactions import topology_overlaps


def compute_gamma1(G2, G4):
    """Compute Gamma1 = 32*|G2| + 256*|G4|.

    This is the numerator coefficient in the alpha variational parameter,
    derived from the first-order counterdiabatic correction with h^x_i = 1.
    """
    return 32 * len(G2) + 256 * len(G4)


def compute_gamma2(lam, G2, G4, I_vals):
    """Compute Gamma2 at schedule parameter lambda.

    Gamma2 = -256 * (topology_term + sum_G2 + sum_G4)
    where:
        topology_term = 4*lam^2*(4*I_24 + I_22) + 64*lam^2*I_44
        sum_G2 = |G2| * 2 * lam^2
        sum_G4 = 4*|G4| * (16*lam^2 + 8*(1-lam)^2)
    """
    lam2 = lam * lam
    topology_term = 4 * lam2 * (4 * I_vals["24"] + I_vals["22"]) + 64 * lam2 * I_vals["44"]
    sum_G2 = len(G2) * 2 * lam2
    sum_G4 = 4 * len(G4) * (16 * lam2 + 8 * (1 - lam) ** 2)
    return -256 * (topology_term + sum_G2 + sum_G4)


def compute_theta(t, dt, total_time, N, G2, G4):
    """Compute theta parameter for counterdiabatic optimization.

    Uses trigonometric annealing schedule:
        lambda(t) = sin^2(pi*t / (2*T))
        lambda_dot(t) = (pi/(2*T)) * sin(pi*t / T)

    Then:
        alpha = -Gamma1 / Gamma2
        theta = dt * alpha * lambda_dot
    """
    if total_time == 0:
        return 0.0

    arg = (pi * t) / (2.0 * total_time)
    lam = sin(arg) ** 2
    lam_dot = (pi / (2.0 * total_time)) * sin((pi * t) / total_time)

    Gamma1 = compute_gamma1(G2, G4)
    I_vals = topology_overlaps(G2, G4)
    Gamma2 = compute_gamma2(lam, G2, G4, I_vals)

    if abs(Gamma2) < 1e-12:
        return 0.0

    alpha = -Gamma1 / Gamma2
    return dt * alpha * lam_dot
