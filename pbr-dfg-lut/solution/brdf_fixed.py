#!/usr/bin/env python3

"""
Fixed brdf.py — corrected BRDF integration functions.

Fixes applied:
1. dfv_multiscatter: use multiscatter Fresnel decomposition
   (r_x += v * Fc, r_y += v) instead of single-scatter
   (r_x += v * (1-Fc), r_y += v * Fc)
2. d_charlie: correct NDF exponent to inv_alpha * 0.5
   (was inv_alpha, doubling the effective sharpness)
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sampler import hammersley, importance_sample_ggx, hemisphere_uniform_sample

PI = math.pi


def saturate(x):
    return max(0.0, min(1.0, x))


def pow5(x):
    x2 = x * x
    return x2 * x2 * x


def v_smith_ggx_correlated(NoV, NoL, a):
    """Height-correlated Smith-GGX visibility function."""
    a2 = a * a
    GGXL = NoV * math.sqrt(max(0.0, (NoL - NoL * a2) * NoL + a2))
    GGXV = NoL * math.sqrt(max(0.0, (NoV - NoV * a2) * NoV + a2))
    denom = GGXV + GGXL
    if denom < 1e-7:
        return 0.0
    return 0.5 / denom


def d_charlie(NoH, a):
    """Charlie (Estevez-Kulla) NDF for cloth sheen."""
    if a < 1e-7:
        return 0.0
    inv_alpha = 1.0 / a
    cos2h = NoH * NoH
    sin2h = max(0.0, 1.0 - cos2h)
    # FIX: exponent is inv_alpha * 0.5, not inv_alpha
    return (2.0 + inv_alpha) * math.pow(max(sin2h, 1e-12), inv_alpha * 0.5) / (2.0 * PI)


def v_ashikhmin(NoV, NoL):
    """Neubelt-Pettineo visibility for cloth."""
    denom = 4.0 * (NoL + NoV - NoL * NoV)
    if denom < 1e-7:
        return 0.0
    return 1.0 / denom


def dfv_multiscatter(NoV, linear_roughness, num_samples):
    """
    Compute multiscatter DFG values (DFG1, DFG2) via importance-sampled
    GGX integration.
    """
    r_x = 0.0
    r_y = 0.0
    sin_v = math.sqrt(max(0.0, 1.0 - NoV * NoV))
    V = (sin_v, 0.0, NoV)
    inv_n = 1.0 / num_samples

    for i in range(num_samples):
        u = hammersley(i, inv_n)
        H = importance_sample_ggx(u, linear_roughness)
        VdotH = V[0] * H[0] + V[1] * H[1] + V[2] * H[2]
        L = (
            2.0 * VdotH * H[0] - V[0],
            2.0 * VdotH * H[1] - V[1],
            2.0 * VdotH * H[2] - V[2],
        )
        VoH = saturate(VdotH)
        NoL = saturate(L[2])
        NoH = saturate(H[2])

        if NoL > 0 and NoH > 0:
            v = v_smith_ggx_correlated(NoV, NoL, linear_roughness) * NoL * (VoH / NoH)
            Fc = pow5(1.0 - VoH)
            # FIX: multiscatter decomposition
            r_x += v * Fc
            r_y += v

    return (r_x * 4.0 / num_samples, r_y * 4.0 / num_samples)


def dfv_charlie(NoV, linear_roughness, num_samples):
    """Compute cloth sheen DFG via uniform hemisphere sampling."""
    r = 0.0
    sin_v = math.sqrt(max(0.0, 1.0 - NoV * NoV))
    V = (sin_v, 0.0, NoV)
    inv_n = 1.0 / num_samples

    for i in range(num_samples):
        u = hammersley(i, inv_n)
        H = hemisphere_uniform_sample(u)
        VdotH = V[0] * H[0] + V[1] * H[1] + V[2] * H[2]
        L = (
            2.0 * VdotH * H[0] - V[0],
            2.0 * VdotH * H[1] - V[1],
            2.0 * VdotH * H[2] - V[2],
        )
        VoH = saturate(VdotH)
        NoL = saturate(L[2])
        NoH = saturate(H[2])

        if NoL > 0:
            v = v_ashikhmin(NoV, NoL)
            d = d_charlie(NoH, linear_roughness)
            r += v * d * NoL * VoH

    return r * (4.0 * 2.0 * PI / num_samples)
