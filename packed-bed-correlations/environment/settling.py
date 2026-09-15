"""Terminal settling velocity computation for spherical particles."""

import math

G = 9.80665


def _barati(Re):
    """Barati (2014) drag coefficient for smooth spheres, Re <= 2e5."""
    Re_inv = 1.0 / Re
    return (
        5.4856e9 * math.tanh(4.3774e-9 * Re_inv)
        + 0.0709 * math.tanh(700.6574 * Re_inv)
        + 0.3894 * math.tanh(74.1539 * Re_inv)
        + 0.1198 * math.tanh(7429.0843 * Re_inv)
        + 1.7174 * math.tanh(9.9851 / (Re + 2.3384))
        + 0.4744
    )


def _barati_high(Re):
    """Barati (2014) wide-range drag coefficient, Re <= 1e6."""
    if Re > 1e6:
        Re = 1e6
    Re2 = Re * Re
    t0 = 1.0 / Re
    t1 = Re / 6530.0
    t2 = Re / 1620.0
    t3 = math.log10(Re2 + 10.7563)
    t4 = 1.0 / (Re + Re2)
    t4 = t4 * t4 * t4 * t4
    tanhRe = math.tanh(Re)
    return (
        8e-6 * (t1 * t1 + tanhRe - 8.0 * math.log10(Re))
        - 0.4119 * math.exp(-2.08e43 * t4)
        - 2.1344 * math.exp(-t0 * (t3 * t3 + 9.9867))
        + 0.1357 * math.exp(-t0 * (t2 * t2 + 10370.0))
        - 8.5e-3 * t0 * (2.0 * math.log10(math.tanh(tanhRe)) - 2825.7162)
        + 2.4795
    )


def _drag_sphere(Re):
    """Composite drag coefficient with Stokes-Barati blending."""
    if Re > 0.1:
        if Re <= 212963.26847812787:
            return _barati(Re)
        else:
            return _barati_high(Re)
    elif Re >= 0.01:
        ratio = (Re - 0.01) / (0.1 - 0.01)
        return ratio * _barati(Re) + (1.0 - ratio) * (24.0 / Re)
    else:
        return 24.0 / Re


def v_terminal(dp, rho_p, rho_f, mu):
    """Compute terminal settling velocity of a sphere."""
    v_lam = G * dp * dp * (rho_p - rho_f) / (18.0 * mu)
    Re_lam = rho_f * v_lam * dp / mu
    if Re_lam < 0.01:
        return v_lam

    Re_almost = rho_f * dp / mu
    main = 4.0 / 3.0 * G * dp * (rho_p - rho_f) / rho_f
    V_max = 1e6 / rho_f / dp * mu

    def err(V):
        Cd = _drag_sphere(Re_almost * V)
        return V - math.sqrt(main / Cd)

    # Secant method
    x0 = V_max * 1e-2
    f0 = err(x0)
    x1 = x0 * 1.0001 if x0 != 0 else 1e-6
    for _ in range(300):
        f1 = err(x1)
        if abs(f1) < 1e-12 * max(abs(x1), 1e-30):
            return x1
        denom = f1 - f0
        if abs(denom) < 1e-30:
            x1 = x1 * 1.1
            f0 = err(x1 * 0.9)
            x0 = x1 * 0.9
            continue
        x_new = x1 - f1 * (x1 - x0) / denom
        if x_new <= 0:
            x_new = x1 * 0.5
        x0, f0 = x1, f1
        x1 = x_new
    return x1
