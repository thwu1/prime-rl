"""Peng-Robinson cubic EOS for multicomponent mixtures.

"""
from .constants import R, OMEGA_A, OMEGA_B
from .mixing import mix_params
from .cubic import solve_cubic_volumes
from .fugacity import fugacity_coefficients_from_V
from .flash import flash_pt, rachford_rice


def mixture_fugacity_coefficients(T, P, zs, Tcs, Pcs, omegas, kijs, phase='liquid'):
    """Compute fugacity coefficients for each component in the mixture."""
    a_alpha_mix, b_mix, a_alpha_ijs, bs = mix_params(T, Tcs, Pcs, omegas, zs, kijs)
    volumes = solve_cubic_volumes(T, P, a_alpha_mix, b_mix)
    if not volumes:
        raise ValueError("No physical volume root found for the given conditions")
    V = volumes[0] if phase == 'liquid' else volumes[-1]
    return fugacity_coefficients_from_V(T, P, V, zs, a_alpha_mix, b_mix, a_alpha_ijs, bs)
