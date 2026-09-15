"""Wall-corrected packed-bed pressure drop correlations."""

import math

PI = math.pi


def montillet_akkari_comiti(dp, voidage, vs, rho, mu, L=1.0, Dt=None, **_):
    """Montillet, Akkari & Comiti packed-bed pressure drop with wall correction."""
    Re = rho * vs * dp / mu
    a = 0.061 if voidage < 0.4 else 0.05
    if Dt is None or Dt / dp > 50:
        Dterm = 2.2
    else:
        Dterm = (Dt / dp) ** 0.2
    right = a * Dterm * (1000.0 / Re + 60.0 / math.sqrt(Re) + 12.0)
    e3 = voidage * voidage * voidage
    left = dp / (L * rho * vs * vs * (1.0 - voidage)) * e3
    return right / left
