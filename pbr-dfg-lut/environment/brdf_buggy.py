#!/usr/bin/env python3

"""
PBR BRDF component functions for DFG LUT computation.

Implements the Cook-Torrance microfacet model (GGX distribution,
Smith-GGX height-correlated visibility) and Estevez-Kulla cloth
sheen model (Charlie NDF, Ashikhmin visibility).
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
    """
    Height-correlated Smith-GGX visibility function.
    Incorporates the 1/(4*NoV*NoL) Cook-Torrance denominator.
    Reference: Heitz 2014, "Understanding the Masking-Shadowing Function"
    """
    a2 = a * a
    GGXL = NoV * math.sqrt(max(0.0, (NoL - NoL * a2) * NoL + a2))
    GGXV = NoL * math.sqrt(max(0.0, (NoV - NoV * a2) * NoV + a2))
    denom = GGXV + GGXL
    if denom < 1e-7:
        return 0.0
    return 0.5 / denom


def d_charlie(NoH, a):
    """
    Charlie NDF for cloth sheen BRDF.
    Reference: Estevez and Kulla 2017, "Production Friendly Microfacet Sheen BRDF"

    D_Charlie(NoH, a) = (2 + 1/a) * sin2h^(1/(2a)) / (2*pi)
    """
    if a < 1e-7:
        return 0.0
    inv_alpha = 1.0 / a
    cos2h = NoH * NoH
    sin2h = max(0.0, 1.0 - cos2h)
    return (2.0 + inv_alpha) * math.pow(max(sin2h, 1e-12), inv_alpha) / (2.0 * PI)


def v_ashikhmin(NoV, NoL):
    """
    Neubelt-Pettineo visibility for cloth materials.
    Reference: "Crafting a Next-gen Material Pipeline for The Order: 1886"
    """
    denom = 4.0 * (NoL + NoV - NoL * NoV)
    if denom < 1e-7:
        return 0.0
    return 1.0 / denom


def dfv_multiscatter(NoV, linear_roughness, num_samples):
    """
    Compute multiscatter DFG values (DFG1, DFG2) via importance-sampled
    GGX integration.

    Multiscatter assumes f90 = 1, so F(h) = f0*(1-Fc) + Fc, and we
    factor out f0 to allow runtime reconstruction:
        Er() = (1 - f0) * DFG1 + f0 * DFG2 = mix(DFG1, DFG2, f0)

    DFG1 = Fc-weighted visibility integral
    DFG2 = total visibility integral
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
            r_x += v * (1.0 - Fc)
            r_y += v * Fc

    return (r_x * 4.0 / num_samples, r_y * 4.0 / num_samples)


def dfv_charlie(NoV, linear_roughness, num_samples):
    """
    Compute cloth sheen DFG via uniform hemisphere sampling with
    Charlie NDF and Ashikhmin visibility.

    Uses uniform sampling because Charlie NDF importance sampling
    has numerical instability at low roughness values.
    """
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
