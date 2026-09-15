"""Advanced packed-bed pressure drop correlations."""

import math


def erdim_akgiray_demir(dp, voidage, vs, rho, mu, L=1.0, **_):
    """Erdim, Akgiray & Demir (2015) packed-bed pressure drop correlation."""
    h = 1.0 - voidage
    e3 = voidage * voidage * voidage
    Rem = dp * rho * vs / (h * mu)
    fv = 160.0 + 2.81 * Rem ** 0.904
    return fv * (mu * vs * L / (dp * dp)) * h * h / e3


def fahien_schriver(dp, voidage, vs, rho, mu, L=1.0, **_):
    """Fahien & Schriver (1961) packed-bed pressure drop correlation."""
    h = 1.0 - voidage
    v2 = voidage * voidage
    e3 = v2 * voidage
    Rem = dp * rho * vs / (h * mu)
    q = math.exp(-v2 * (1.0 / 12.6) * Rem)
    f1L = 136.0 / h ** 0.38
    f1T = 29.0 / (h ** 1.45 * v2)
    f2 = 1.87 * voidage ** 0.75 / h ** 0.26
    fp = (q * f1L / Rem + (1.0 - q) * (f2 + f1T / Rem)) * h / e3
    return fp * rho * vs * vs * L / dp
