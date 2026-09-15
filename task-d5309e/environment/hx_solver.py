"""TEMA E shell-and-tube heat exchanger P-NTU solver.

Work in progress. Some tube-pass configurations produce incorrect results
or are not yet implemented.

"""
import math


def temperature_effectiveness_TEMA_E(R1, NTU1, Ntp=1, optimal=True):
    """Compute shell-side temperature effectiveness P1 for a TEMA E shell.

    Parameters
    ----------
    R1 : float
        Shell-side heat capacity ratio C1/C2
    NTU1 : float
        Shell-side number of transfer units UA/C1
    Ntp : int
        Number of tube passes
    optimal : bool
        True for optimal flow arrangement

    Returns
    -------
    P1 : float
        Shell-side temperature effectiveness
    """
    if Ntp == 1:
        # Counterflow
        if abs(R1 - 1.0) < 1e-12:
            return NTU1 / (1.0 + NTU1)
        exp_val = math.exp(-NTU1 * (1.0 - R1))
        return (1.0 - exp_val) / (1.0 - R1 * exp_val)

    elif Ntp == 2 and optimal:
        # 1-2 TEMA E, optimal (symmetric) arrangement
        E = math.sqrt(1.0 + R1**2)
        coth_term = E / math.tanh(E * NTU1 / 2.0)
        return 2.0 / (1.0 + R1 + coth_term)

    elif Ntp == 2 and not optimal:
        # 1-2 TEMA E, non-optimal arrangement
        # NOTE: using same formula as optimal as placeholder
        E = math.sqrt(1.0 + R1**2)
        coth_term = E / math.tanh(E * NTU1 / 2.0)
        return 2.0 / (1.0 + R1 + coth_term)

    elif Ntp == 3:
        raise NotImplementedError(
            "3 tube pass configurations not yet supported"
        )

    elif Ntp % 2 == 0 and Ntp >= 4:
        # General even-N formula
        # Convention swap: work with tube-side variables
        NTU2 = NTU1 * R1
        R2 = 1.0 / R1
        N1 = Ntp  # sub-exchanger count

        C = (1.0 / N1) * math.sqrt(1 + N1**2 * R2**2) / math.tanh(
            NTU2 / (2 * N1) * math.sqrt(1 + N1**2 * R2**2))
        B = (-1.0 / N1) / math.tanh(NTU2 / (2 * N1))
        A = 1.0 + R2 + 1.0 / math.tanh(NTU2 / 2.0)

        P2 = 2.0 / (A + B + C)
        return P2 / R1  # Convert back to P1

    else:
        raise ValueError(
            f"Odd tube pass count Ntp={Ntp} > 3 is not supported"
        )


def NTU_from_P_E(P1, R1, Ntp, optimal=True):
    """Recover NTU1 from known P1 and R1 for TEMA E shell.

    Parameters
    ----------
    P1 : float
        Shell-side temperature effectiveness
    R1 : float
        Shell-side heat capacity ratio
    Ntp : int
        Number of tube passes
    optimal : bool
        True for optimal flow arrangement

    Returns
    -------
    NTU1 : float
        Number of transfer units
    """
    if Ntp == 1:
        # Counterflow analytical inverse
        if abs(R1 - 1.0) < 1e-12:
            return P1 / (1.0 - P1)
        return (1.0 / (R1 - 1.0)) * math.log((P1 - 1.0) / (P1 * R1 - 1.0))

    else:
        raise NotImplementedError(
            f"NTU inversion for Ntp={Ntp} not yet implemented"
        )


def P_NTU_method(m1, m2, Cp1, Cp2, UA=None, T1i=None, T1o=None,
                 T2i=None, T2o=None, Ntp=1, optimal=True):
    """Solve a TEMA E heat exchanger using the P-NTU method.

    Side 1 = shell, side 2 = tube.

    Parameters
    ----------
    m1, m2 : float
        Mass flow rates [kg/s]
    Cp1, Cp2 : float
        Specific heat capacities [J/(kg*K)]
    UA : float or None
        Overall heat transfer coefficient times area [W/K]
    T1i, T1o : float or None
        Shell-side inlet/outlet temperatures
    T2i, T2o : float or None
        Tube-side inlet/outlet temperatures
    Ntp : int
        Number of tube passes
    optimal : bool
        Optimal flow arrangement

    Returns
    -------
    dict
        Keys: Q, UA, T1i, T1o, T2i, T2o, P1, P2, R1, R2, C1, C2, NTU1, NTU2
    """
    C1 = m1 * Cp1
    C2 = m2 * Cp2
    R1 = C1 / C2
    R2 = C2 / C1

    if UA is not None:
        NTU1 = UA / C1
        NTU2 = UA / C2
        P1 = temperature_effectiveness_TEMA_E(
            R1=R1, NTU1=NTU1, Ntp=Ntp, optimal=optimal)

        # Determine unknown temperatures
        if T1i is not None and T2i is not None:
            T1o = T1i - P1 * (T1i - T2i)
            T2o = T2i + P1 * R1 * (T1i - T2i)
        else:
            raise ValueError(
                "Forward mode currently only supports T1i and T2i as inputs"
            )
    else:
        raise ValueError("Inverse mode (UA unknown) not yet implemented")

    Q = C1 * (T1i - T1o)
    P2 = P1 * R1

    return {
        "Q": Q, "T1i": T1i, "T1o": T1o, "T2i": T2i, "T2o": T2o,
        "C1": C1, "C2": C2, "R1": R1, "R2": R2,
        "P1": P1, "P2": P2, "NTU1": NTU1, "NTU2": NTU2, "UA": UA,
    }
