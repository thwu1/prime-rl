"""TEMA E shell-and-tube heat exchanger P-NTU solver.

"""
from math import exp, log, sqrt, tanh

from scipy.optimize import brentq, minimize_scalar


# ============================================================
# temperature_effectiveness_TEMA_E
# ============================================================

def temperature_effectiveness_TEMA_E(R1, NTU1, Ntp=1, optimal=True):
    """Return temperature effectiveness P1 for a TEMA E shell.

    Side 1 = shell, side 2 = tube.
    """
    if Ntp == 1:
        # Pure counterflow
        if R1 != 1:
            P1 = (1 - exp(-NTU1 * (1 - R1))) / (1 - R1 * exp(-NTU1 * (1 - R1)))
        else:
            P1 = NTU1 / (1.0 + NTU1)

    elif Ntp == 2 and optimal:
        # 1-2 TEMA E, shell fluid mixed (symmetric)
        if R1 != 1:
            E = (1.0 + R1 ** 2) ** 0.5
            P1 = 2.0 / (1 + R1 + E / tanh(E * NTU1 / 2.0))
        else:
            P1 = 1 / (1 + 1 / tanh(NTU1 * 2 ** -0.5) * 2 ** -0.5)

    elif Ntp == 2 and not optimal:
        # 1-2 TEMA E, shell fluid split into two streams individually mixed
        A = exp(NTU1)
        B = exp(-NTU1 * R1 / 2.0)
        if R1 != 2:
            P1 = 1 / R1 * (1 - (2 - R1) * (2 * A + R1 * B) / (2 + R1) / (2 * A - R1 / B))
        else:
            P1 = 0.5 * (1 - (1 + A ** -2) / 2.0 / (1 + NTU1))

    elif Ntp == 3 and optimal:
        # Eigenvalue-based formula
        lambda3 = R1
        lambda2 = -1.5 - (2.25 + R1 * (R1 - 1)) ** 0.5
        lambda1 = -1.5 + (2.25 + R1 * (R1 - 1)) ** 0.5
        delta = lambda1 - lambda2
        X1 = exp(lambda1 * NTU1 / 3.0) / 2 / delta
        X2 = exp(lambda2 * NTU1 / 3.0) / 2 / delta
        X3 = exp(lambda3 * NTU1 / 3.0) / 2 / delta
        C = X2 * (3 * R1 + lambda1) - X1 * (3 * R1 + lambda2) + X3 * delta
        B_val = X1 * (R1 - lambda2) - X2 * (R1 - lambda1) + X3 * delta
        if R1 != 1:
            A = (X1 * (R1 + lambda1) * (R1 - lambda2) / 2 / lambda1
                 - X3 * delta
                 - X2 * (R1 + lambda2) * (R1 - lambda1) / 2 / lambda2
                 + 1.0 / (1 - R1))
        else:
            A = -exp(-NTU1) / 18 - exp(NTU1 / 3.0) / 2 + (NTU1 + 5) / 9.0
        P1 = 1.0 / R1 * (1.0 - C / (A * C + B_val * B_val))

    elif Ntp == 3 and not optimal:
        # Convention swap: work with R2=1/R1, NTU2=NTU1*R1
        R1_orig = R1
        NTU1 = NTU1 * R1_orig  # NTU2
        R1 = 1.0 / R1_orig     # R2

        delta = (9 * R1 ** 2 + 4 * (1 - R1)) ** 0.5 / R1
        l1 = (-3 + delta) / 2.0
        l2 = (-3 - delta) / 2.0
        chi1 = exp(l1 * R1 * NTU1 / 3.0) / 2 / delta
        chi2 = exp(l2 * R1 * NTU1 / 3.0) / 2 / delta
        E = 0.5 * exp(NTU1 / 3.0)
        C = -chi1 * (3 + R1 * l2) / R1 + chi2 * (3 + R1 * l1) / R1 + E
        B_val = chi1 * (1 - R1 * l2) / R1 - chi2 * (1 - R1 * l1) / R1 + E
        A = (chi1 * (1 + R1 * l1) * (1 - R1 * l2) / (2 * R1 ** 2 * l1)
             - E
             - chi2 * (1 + R1 * l2) * (1 - R1 * l1) / (2 * R1 ** 2 * l2)
             + R1 * (R1 - 1))
        P1 = (1 - C / (A * C + B_val ** 2))
        P1 = P1 / R1_orig  # convert P2 back to P1

    elif Ntp == 4 or Ntp % 2 == 0:
        # General even-N formula (Thulukkanam)
        R1_orig = R1
        NTU1 = NTU1 * R1_orig  # NTU2
        R1 = 1.0 / R1_orig     # R2

        N1 = Ntp / 2.0
        C = 1 / N1 * (1 + N1 ** 2 * R1 ** 2) ** 0.5 / tanh(NTU1 / (2 * N1) * (1 + N1 ** 2 * R1 ** 2) ** 0.5)
        B_val = -1 / N1 / tanh(NTU1 / (2 * N1))
        A = 1 + R1 + 1 / tanh(NTU1 / 2.0)
        P1 = 2 / (A + B_val + C)
        P1 = P1 / R1_orig  # convert P2 back to P1

    else:
        raise ValueError("For TEMA E shells with an odd number of tube passes "
                         "more than 3, no solution is implemented.")
    return P1


# ============================================================
# NTU_from_P_E
# ============================================================

def _NTU_from_P_basic_counterflow(P1, R1):
    """Analytical inverse for counterflow (1 tube pass)."""
    if R1 == 1:
        return P1 / (1.0 - P1)
    else:
        return 1.0 / (R1 - 1.0) * log((P1 - 1.0) / (P1 * R1 - 1.0))


def NTU_from_P_E(P1, R1, Ntp, optimal=True):
    """Invert temperature_effectiveness_TEMA_E to recover NTU1."""
    if Ntp == 1:
        return _NTU_from_P_basic_counterflow(P1, R1)

    elif Ntp == 2 and optimal:
        # Analytical solution
        x1 = R1 * R1 + 1.0
        return 2.0 * log(((P1 * R1 - P1 * x1 ** 0.5 + P1 - 2.0)
                          / (P1 * R1 + P1 * x1 ** 0.5 + P1 - 2.0)) ** 0.5) * x1 ** -0.5

    else:
        # Numerical root-finding
        if Ntp == 2 and not optimal:
            NTU_max = 100.0
        elif Ntp == 3:
            NTU_max = 10.0
        elif Ntp % 2 == 0:
            NTU_max = 1000.0
        else:
            raise ValueError("For TEMA E shells with an odd number of tube passes "
                             "more than 3, no solution is implemented.")

        NTU_min = 1e-11

        def objective(NTU1):
            return temperature_effectiveness_TEMA_E(R1, NTU1, Ntp, optimal) - P1

        # For even-N passes, the effectiveness can be non-monotonic.
        # Find the actual maximum P1 achievable and use that NTU as the upper bound.
        P1_at_max = temperature_effectiveness_TEMA_E(R1, NTU_max, Ntp, optimal)
        P1_at_min = temperature_effectiveness_TEMA_E(R1, NTU_min, Ntp, optimal)

        if P1 > P1_at_max and Ntp >= 4 and Ntp % 2 == 0:
            # The even-N effectiveness can peak then decrease.
            # Sample to find approximate peak, then refine.
            best_ntu = NTU_min
            best_p1 = P1_at_min
            # Log-spaced sampling to find approximate peak
            import numpy as np
            for ntu_sample in np.logspace(-10, np.log10(NTU_max), 200):
                p1_sample = temperature_effectiveness_TEMA_E(R1, ntu_sample, Ntp, optimal)
                if p1_sample > best_p1:
                    best_p1 = p1_sample
                    best_ntu = ntu_sample

            # Refine the peak with minimize_scalar around the approximate location
            lo = max(NTU_min, best_ntu / 5.0)
            hi = min(NTU_max, best_ntu * 5.0)
            res = minimize_scalar(
                lambda ntu: -temperature_effectiveness_TEMA_E(R1, ntu, Ntp, optimal),
                bounds=(lo, hi), method='bounded'
            )
            NTU_peak = res.x
            P1_peak = -res.fun
            if P1 > P1_peak * (1 + 1e-6):
                raise ValueError(f"No solution: P1={P1} exceeds max achievable P1={P1_peak}")
            NTU_max = NTU_peak

        elif P1 > P1_at_max:
            raise ValueError(f"No solution: P1={P1} exceeds max P1={P1_at_max} at NTU1={NTU_max}")

        if P1 < P1_at_min:
            raise ValueError(f"No solution: P1={P1} below min P1={P1_at_min} at NTU1={NTU_min}")

        return brentq(objective, NTU_min, NTU_max, xtol=1e-13)


# ============================================================
# P_NTU_method
# ============================================================

def P_NTU_method(m1, m2, Cp1, Cp2, UA=None, T1i=None, T1o=None,
                 T2i=None, T2o=None, Ntp=1, optimal=True):
    """Solve a TEMA E heat exchanger using the P-NTU method.

    Side 1 = shell, side 2 = tube.
    """
    C1 = m1 * Cp1
    C2 = m2 * Cp2
    R1 = C1 / C2
    R2 = C2 / C1

    if UA is not None:
        NTU1 = UA / C1
        NTU2 = UA / C2

        P1 = temperature_effectiveness_TEMA_E(R1=R1, NTU1=NTU1, Ntp=Ntp, optimal=optimal)

        # Compute unknown temperatures from known pair
        if T1i is not None and T2i is not None:
            T2o = P1 * R1 * T1i - P1 * R1 * T2i + T2i
            T1o = -P1 * T1i + P1 * T2i + T1i
        elif T1o is not None and T2o is not None:
            T2i = (P1 * R1 * T1o + P1 * T2o - T2o) / (P1 * R1 + P1 - 1.0)
            T1i = (P1 * R1 * T1o + P1 * T2o - T1o) / (P1 * R1 + P1 - 1.0)
        elif T1o is not None and T2i is not None:
            T2o = (R1 * (P1 * T2i - T1o) - (P1 - 1.0) * (R1 * T1o - T2i)) / (P1 - 1.0)
            T1i = (P1 * T2i - T1o) / (P1 - 1.0)
        elif T1i is not None and T2o is not None:
            T1o = (P1 * R1 * T1i + P1 * T1i - P1 * T2o - T1i) / (P1 * R1 - 1.0)
            T2i = (P1 * R1 * T1i - T2o) / (P1 * R1 - 1.0)
        elif T2i is not None and T2o is not None:
            T1o = (P1 * R1 * T2i + (P1 - 1.0) * (T2i - T2o)) / (P1 * R1)
            T1i = (P1 * R1 * T2i - T2i + T2o) / (P1 * R1)
        elif T1i is not None and T1o is not None:
            T2o = (P1 * R1 * (T1i - T1o) + P1 * T1i - T1i + T1o) / P1
            T2i = (P1 * T1i - T1i + T1o) / P1
        else:
            raise ValueError("At least two temperatures are required along with UA.")

    else:
        # Inverse mode: solve for UA from three temperatures
        if T1i is not None and T1o is not None:
            Q = m1 * Cp1 * (T1i - T1o)
            if T2i is not None and T2o is None:
                T2o = T2i + Q / (m2 * Cp2)
            elif T2o is not None and T2i is None:
                T2i = T2o - Q / (m2 * Cp2)
            elif T2o is not None and T2i is not None:
                Q2 = m2 * Cp2 * (T2o - T2i)
                if abs((Q - Q2) / Q) > 0.01:
                    raise ValueError("Inconsistent temperatures and flows")
            else:
                raise ValueError("Need at least one side-2 temperature")
        elif T2i is not None and T2o is not None:
            Q = m2 * Cp2 * (T2o - T2i)
            if T1i is not None and T1o is None:
                T1o = T1i - Q / (m1 * Cp1)
            elif T1o is not None and T1i is None:
                T1i = T1o + Q / (m1 * Cp1)
            else:
                raise ValueError("Need at least one side-1 temperature")
        else:
            raise ValueError("Three temperatures required when solving for UA")

        P1 = abs(T1o - T1i) / abs(T2i - T1i)

        NTU1 = NTU_from_P_E(P1=P1, R1=R1, Ntp=Ntp, optimal=optimal)
        UA = NTU1 * C1
        NTU2 = UA / C2

    Q = abs(T1i - T2i) * P1 * C1
    P2 = P1 * R1

    return {
        "Q": Q, "T1i": T1i, "T1o": T1o, "T2i": T2i, "T2o": T2o,
        "C1": C1, "C2": C2, "R1": R1, "R2": R2,
        "P1": P1, "P2": P2, "NTU1": NTU1, "NTU2": NTU2, "UA": UA,
    }
