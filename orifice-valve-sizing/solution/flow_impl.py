"""Flow analysis module implementing ISO 5167-2 orifice plate metering
and IEC 60534-2-1 control valve sizing.

Uses only the Python standard library (math module). No external packages.
"""

from math import pi, sqrt, exp, log10

# ──────────────────────────────────────────────────────────────────
# Physical constants
# ──────────────────────────────────────────────────────────────────
R_GAS = 8.31446261815324  # Universal gas constant [J/(mol·K)]

# ──────────────────────────────────────────────────────────────────
# IEC 60534 numeric constants (encode specific internal unit choices)
# N1:  m³/hr with kPa
# N2:  mm
# N4:  m³/hr with m²/s
# N5:  mm
# N9:  m³/hr, kPa, K  (standard conditions at 0 °C)
# N18: mm
# N32: mm
# ──────────────────────────────────────────────────────────────────
_N1 = 0.1
_N2 = 1.6e-3
_N4 = 7.07e-2
_N5 = 1.8e-3
_N9 = 2.46e1
_N18 = 8.65e-1
_N32 = 1.4e2
_RHO0 = 999.10329075702327  # Reference water density at 288.15 K [kg/m³]


# ======================================================================
#  ISO 5167-2 — Orifice plate metering
# ======================================================================

def orifice_discharge_coefficient(D, Do, rho, mu, m, taps="corner"):
    """Reader-Harris-Gallagher discharge coefficient for concentric orifice
    plates per ISO 5167-2.

    Parameters
    ----------
    D : float   Pipe inner diameter [m]
    Do : float  Orifice diameter [m]
    rho : float Fluid density [kg/m³]
    mu : float  Dynamic viscosity [Pa·s]
    m : float   Mass flow rate [kg/s]
    taps : str  Tap type: "corner", "flange", or "D"

    Returns
    -------
    C : float   Discharge coefficient [-]
    """
    A_pipe = 0.25 * pi * D * D
    v = m / (A_pipe * rho)
    Re_D = rho * v * D / mu
    Re_D_inv = 1.0 / Re_D

    beta = Do / D
    beta2 = beta * beta
    beta4 = beta2 * beta2
    beta8 = beta4 * beta4

    # Tap-type-dependent geometric parameters
    if taps == "corner":
        L1 = 0.0
        L2_prime = 0.0
    elif taps == "flange":
        L1 = L2_prime = 0.0254 / D
    elif taps in ("D", "D/2"):
        L1 = 1.0
        L2_prime = 0.47
    else:
        raise ValueError(f"Unsupported tap type: {taps}")

    A = (19000.0 * beta * Re_D_inv) ** 0.8
    M2_prime = 2.0 * L2_prime / (1.0 - beta)

    # Upstream tap correction term
    expnL1 = exp(-L1)
    expnL2 = expnL1 * expnL1       # exp(-2·L1)
    expnL3 = expnL1 * expnL2       # exp(-3·L1)
    # 0.043 + 0.080·exp(-10·L1) - 0.123·exp(-7·L1)
    delta_C_upstream = (
        (0.043 + expnL3 * expnL2 * expnL2 * (0.080 * expnL3 - 0.123))
        * (1.0 - 0.11 * A) * beta4 / (1.0 - beta4)
    )

    # Downstream tap correction term
    t1 = log10(3700.0 * Re_D_inv)
    if t1 < 0.0:
        t1 = 0.0
    delta_C_downstream = (
        -0.031 * (M2_prime - 0.8 * M2_prime ** 1.1) * beta ** 1.3
        * (1.0 + 8.0 * t1)
    )

    # C∞ + slope term
    x1 = (1e6 * Re_D_inv) ** 0.3
    x2 = 22.7 - 0.0047 * Re_D
    t2 = max(x2, x1)

    C_inf_C_s = (
        0.5961
        + 0.0261 * beta2
        - 0.216 * beta8
        + 0.000521 * (1e6 * beta * Re_D_inv) ** 0.7
        + (0.0188 + 0.0063 * A) * beta2 * beta * sqrt(beta) * t2
    )

    C = C_inf_C_s + delta_C_upstream + delta_C_downstream

    # Small-diameter correction (D < 71.12 mm = 2.8 in.)
    if D < 0.07112:
        t3 = 2.8 - D / 0.0254
        delta_C_diameter = 0.011 * (0.75 - beta) * t3
        C += delta_C_diameter

    return C


def orifice_expansibility(D, Do, P1, P2, k):
    """ISO 5167-2 expansibility factor ε for orifice plates.

    Parameters
    ----------
    D : float   Pipe inner diameter [m]
    Do : float  Orifice diameter [m]
    P1 : float  Upstream absolute pressure [Pa]
    P2 : float  Downstream absolute pressure [Pa]
    k : float   Isentropic exponent [-]

    Returns
    -------
    eps : float Expansibility factor [-]
    """
    beta = Do / D
    beta2 = beta * beta
    beta4 = beta2 * beta2
    return 1.0 - (0.351 + beta4 * (0.93 * beta4 + 0.256)) * (
        1.0 - (P2 / P1) ** (1.0 / k)
    )


def solve_orifice_flow_rate(D, Do, P1, P2, rho, mu, k, taps="corner"):
    """Iteratively solve for mass flow rate through an ISO 5167 orifice plate.

    C depends on Re_D which depends on m, requiring iteration.

    Parameters
    ----------
    D : float   Pipe inner diameter [m]
    Do : float  Orifice diameter [m]
    P1 : float  Upstream absolute pressure [Pa]
    P2 : float  Downstream absolute pressure [Pa]
    rho : float Fluid density [kg/m³]
    mu : float  Dynamic viscosity [Pa·s]
    k : float   Isentropic exponent [-]
    taps : str  Tap type

    Returns
    -------
    m : float   Mass flow rate [kg/s]
    """
    beta = Do / D
    beta2 = beta * beta
    beta4 = beta2 * beta2
    dP = P1 - P2
    eps = orifice_expansibility(D, Do, P1, P2, k)

    D_beta = D * beta  # = Do
    coeff = 0.25 * pi * D_beta * D_beta * eps * sqrt(2.0 * rho * dP / (1.0 - beta4))

    # Fixed-point iteration: guess C → compute m → compute new C
    C = 0.6  # initial guess
    for _ in range(200):
        m = coeff * C
        C_new = orifice_discharge_coefficient(D, Do, rho, mu, m, taps)
        if abs(C_new - C) < 1e-12 * abs(C_new):
            C = C_new
            break
        C = C_new

    return coeff * C


# ======================================================================
#  IEC 60534-2-1 — Control valve sizing (internal helpers)
# ======================================================================

def _loss_coefficient_piping(d, D1=None, D2=None):
    """Sum of loss coefficients from inlet/outlet reducers/expanders
    per IEC 60534-2-1.  d, D1, D2 in consistent units (mm in practice)."""
    loss = 0.0
    if D1 is not None:
        dr = d / D1
        dr2 = dr * dr
        loss += 1.0 - dr2 * dr2            # Inlet Bernoulli term (ξ_B1)
        loss += 0.5 * (1.0 - dr2) ** 2     # Inlet reducer (ξ_1)
    if D2 is not None:
        dr = d / D2
        dr2 = dr * dr
        loss += 1.0 * (1.0 - dr2) ** 2     # Outlet expander (ξ_2)
        loss -= 1.0 - dr2 * dr2            # Outlet Bernoulli term (-ξ_B2)
    return loss


def _FF_l(Psat, Pc):
    """Liquid critical pressure ratio factor FF."""
    return 0.96 - 0.28 * sqrt(Psat / Pc)


def _is_choked_l(dP, P1, Psat, FF, FL=None, FLP=None, FP=None):
    """Test choked-flow condition for liquid service."""
    if FLP is not None and FP is not None:
        return dP >= (FLP * FLP) / (FP * FP) * (P1 - FF * Psat)
    elif FL is not None:
        return dP >= FL * FL * (P1 - FF * Psat)
    raise ValueError("Need FL or (FLP, FP)")


# ======================================================================
#  IEC 60534-2-1 — Liquid valve sizing
# ======================================================================

def size_liquid_valve(rho, Psat, Pc, mu, P1, P2, Q,
                      D1=None, D2=None, d=None, FL=0.9, Fd=1.0):
    """Size a control valve for liquid service per IEC 60534-2-1.

    Returns metric valve flow coefficient Kv [m³/hr].
    """
    # Convert SI inputs to IEC internal units
    P1k = P1 * 1e-3        # Pa → kPa
    P2k = P2 * 1e-3
    Psk = Psat * 1e-3
    Pck = Pc * 1e-3
    Qh = Q * 3600.0        # m³/s → m³/hr

    dP = P1k - P2k
    FF = _FF_l(Psk, Pck)
    choked = _is_choked_l(dP, P1k, Psk, FF, FL=FL)

    # Initial Kv without piping effects
    if choked:
        C = Qh / _N1 / FL * sqrt(rho / _RHO0 / (P1k - FF * Psk))
    else:
        C = Qh / _N1 * sqrt(rho / _RHO0 / dP)

    # Early return when no diameters are specified
    if D1 is None and D2 is None and d is None:
        return C

    # Convert diameters to mm (IEC internal unit for N2)
    D1m = D1 * 1000.0
    D2m = D2 * 1000.0
    dm = d * 1000.0

    # Piping geometry iteration (turbulent)
    if D1m != dm or D2m != dm:
        _MAX = 40
        for _ in range(_MAX):
            Ci = C
            loss = _loss_coefficient_piping(dm, D1m, D2m)
            FP = 1.0 / sqrt(1.0 + loss / _N2 * (Ci / dm ** 2) ** 2)

            if dm > D1m:
                loss_up = 0.0
            else:
                loss_up = _loss_coefficient_piping(dm, D1m)

            FLP = FL / sqrt(
                1.0 + FL ** 2 / _N2 * loss_up * (Ci / dm ** 2) ** 2
            )
            choked = _is_choked_l(dP, P1k, Psk, FF, FLP=FLP, FP=FP)

            if choked:
                C = Qh / _N1 / FLP * sqrt(rho / _RHO0 / (P1k - FF * Psk))
            else:
                C = Qh / _N1 / FP * sqrt(rho / _RHO0 / dP)

            if Ci / C >= 0.99:
                break

    return C


# ======================================================================
#  IEC 60534-2-1 — Gas valve sizing
# ======================================================================

def size_gas_valve(T, MW, mu, gamma, Z, P1, P2, Q,
                   D1=None, D2=None, d=None, FL=0.9, Fd=1.0, xT=0.7):
    """Size a control valve for gas service per IEC 60534-2-1.

    Q is volumetric flow at 273.15 K and 101325 Pa [m³/s].
    Returns metric valve flow coefficient Kv [m³/hr].
    """
    P1k = P1 * 1e-3        # Pa → kPa
    P2k = P2 * 1e-3
    Qh = Q * 3600.0        # m³/s → m³/hr

    # Gas density for Reynolds check
    Vm = Z * R_GAS * T / (P1k * 1000.0)   # P1 back to Pa for ideal gas
    rho_gas = MW * 1e-3 / Vm              # kg/m³

    dP = P1k - P2k
    Fgamma = gamma / 1.40
    x = dP / P1k
    # Y is computed ONCE using xT (before any piping iteration)
    Y = max(1.0 - x / (3.0 * Fgamma * xT), 2.0 / 3.0)

    choked = x >= Fgamma * xT

    if choked:
        C = Qh / (_N9 * P1k * Y) * sqrt(MW * T * Z / xT / Fgamma)
    else:
        C = Qh / (_N9 * P1k * Y) * sqrt(MW * T * Z / x)

    if D1 is None and D2 is None and d is None:
        return C

    D1m = D1 * 1000.0
    D2m = D2 * 1000.0
    dm = d * 1000.0

    if D1m != dm or D2m != dm:
        _MAX = 40
        for _ in range(_MAX):
            Ci = C
            loss = _loss_coefficient_piping(dm, D1m, D2m)
            FP = 1.0 / sqrt(1.0 + loss / _N2 * (Ci / dm ** 2) ** 2)

            loss_up = _loss_coefficient_piping(dm, D1m)
            xTP = xT / FP ** 2 / (
                1.0 + xT * loss_up / _N5 * (Ci / dm ** 2) ** 2
            )
            choked = x >= Fgamma * xTP

            if choked:
                C = Qh / (_N9 * FP * P1k * Y) * sqrt(
                    MW * T * Z / xTP / Fgamma
                )
            else:
                C = Qh / (_N9 * FP * P1k * Y) * sqrt(MW * T * Z / x)

            if Ci / C >= 0.99:
                break

    return C
