"""Fugacity coefficient calculation for PR EOS mixtures.

"""
import math
from .constants import R, _sqrt2


def fugacity_coefficients_from_V(T, P, V, zs, a_alpha_mix, b_mix, a_alpha_ijs, bs):
    """Compute fugacity coefficients from a given molar volume root.

    Uses the standard PR mixture departure function for ln(phi_i).
    """
    N = len(zs)
    RT = R * T
    Z = P * V / RT
    A = a_alpha_mix * P / (RT * RT)
    B = b_mix * P / RT

    log_ratio = math.log(
        (Z + (1.0 + _sqrt2) * B) / (Z + (1.0 - _sqrt2) * B)
    )
    coeff = A / (2.0 * _sqrt2 * B)

    phis = []
    for i in range(N):
        # Composition-weighted cross parameter sum
        s = sum(zs[j] * a_alpha_ijs[i][j] for j in range(N))

        bi_b = bs[i] / b_mix

        ln_phi = (
            bi_b * (Z - 1.0)
            - math.log(Z - B)
            - coeff * (s / a_alpha_mix - bi_b) * log_ratio
        )
        phis.append(math.exp(ln_phi))

    return phis
