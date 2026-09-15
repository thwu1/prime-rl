"""F_LMTD correction factor for shell-and-tube heat exchangers.

"""
import math


def F_LMTD_Fakheri(Thi, Tho, Tci, Tco, shells=1):
    """Fakheri LMTD correction factor Ft.

    Parameters
    ----------
    Thi, Tho : float
        Hot-side inlet and outlet temperatures
    Tci, Tco : float
        Cold-side inlet and outlet temperatures
    shells : int
        Number of shell passes

    Returns
    -------
    Ft : float
        Correction factor
    """
    R = (Thi - Tho) / (Tco - Tci)
    P = (Tco - Tci) / (Thi - Tci)

    W = ((1.0 - P * R) / (1.0 - P)) ** (1.0 / shells)
    S = math.sqrt(R * R + 1.0) / (R - 1.0)
    return S * math.log(W) / math.log(
        (1.0 + W - S + S * W) / (1.0 + W + S - S * W)
    )
