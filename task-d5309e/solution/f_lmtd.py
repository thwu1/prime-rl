"""F_LMTD correction factor for shell-and-tube heat exchangers.

"""
from math import log


def F_LMTD_Fakheri(Thi, Tho, Tci, Tco, shells=1):
    """Fakheri's LMTD correction factor Ft.

    Parameters
    ----------
    Thi : float
        Hot-side inlet temperature [K or any consistent unit]
    Tho : float
        Hot-side outlet temperature [K]
    Tci : float
        Cold-side inlet temperature [K]
    Tco : float
        Cold-side outlet temperature [K]
    shells : int
        Number of shell passes (default 1)

    Returns
    -------
    Ft : float
        Correction factor [-]
    """
    R = (Thi - Tho) / (Tco - Tci)
    P = (Tco - Tci) / (Thi - Tci)

    if R == 1.0:
        W2 = (shells - shells * P) / (shells - shells * P + P)
        return (2 ** 0.5 * (1.0 - W2) / W2) / log(
            (W2 / (1.0 - W2) + 2 ** -0.5) / (W2 / (1.0 - W2) - 2 ** -0.5)
        )
    else:
        W = ((1.0 - P * R) / (1.0 - P)) ** (1.0 / shells)
        S = (R * R + 1.0) ** 0.5 / (R - 1.0)
        return S * log(W) / log(
            (1.0 + W - S + S * W) / (1.0 + W + S - S * W)
        )
