"""Minimum fluidization velocity computation via root-finding."""

G = 9.80665


def compute_vmf(corr_func, dp, voidage, rho_f, mu, rho_p, Dt=None):
    """Find the superficial velocity at which the pressure drop per unit
    bed length equals the buoyant bed weight per unit length.

    Uses bisection on: corr_func(vs, L=1) - bed_weight = 0
    """
    bed_weight = (1.0 - voidage) * (rho_p - rho_f) * G

    def obj(vs):
        return corr_func(
            dp=dp, voidage=voidage, vs=vs, rho=rho_f, mu=mu, L=1.0, Dt=Dt
        ) - bed_weight

    lo = 1e-15
    hi = 0.5

    # Bisection
    for _ in range(300):
        mid = 0.5 * (lo + hi)
        if mid <= 0:
            mid = 1e-15
        if obj(mid) > 0:
            hi = mid
        else:
            lo = mid
        if hi - lo < 1e-14 * max(mid, 1e-30):
            break
    return 0.5 * (lo + hi)
