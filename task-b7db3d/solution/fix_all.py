#!/usr/bin/env python3
"""Fix all bugs and implement all missing functions in the PBR pipeline.

GGX Bug Fixes:
  1. brdf.py D_GGX: numerator uses alpha instead of alpha^2
  2. brdf.py V_SmithGGXCorrelated: uses fast linear approximation instead of exact sqrt form
  3. brdf.py F_Schlick: uses 4th power instead of 5th power
  4. sampling.py importance_sample_GGX: uses alpha instead of alpha^2 in cos_theta formula
  5. dfg_generator.py compute_dfg weight: missing NoL factor
  6. dfg_generator.py compute_dfg: uses perceptual roughness directly instead of squaring

Cloth Implementation:
  7. brdf.py D_Charlie: Charlie/Estevez-Kulla NDF
  8. brdf.py V_Neubelt: Neubelt visibility for cloth
  9. sampling.py importance_sample_Charlie: Charlie distribution sampling
  10. dfg_generator.py compute_dfg_cloth: cloth DFG integration

Multi-scattering Implementation:
  11. dfg_generator.py compute_dfg_multiscatter: Kulla-Conty energy compensation with E_avg
"""

CORRECTED_BRDF = '''\
"""PBR BRDF component functions following Filament's rendering model."""
import math


def D_GGX(NoH, alpha):
    """GGX/Trowbridge-Reitz Normal Distribution Function."""
    a2 = alpha * alpha
    f = NoH * NoH * (a2 - 1.0) + 1.0
    return a2 / (math.pi * f * f)


def V_SmithGGXCorrelated(NoV, NoL, alpha):
    """Height-correlated Smith-GGX Visibility function (exact sqrt form)."""
    a2 = alpha * alpha
    GGXV = NoL * math.sqrt(NoV * NoV * (1.0 - a2) + a2)
    GGXL = NoV * math.sqrt(NoL * NoL * (1.0 - a2) + a2)
    return 0.5 / (GGXV + GGXL + 1e-7)


def F_Schlick(u, f0, f90=1.0):
    """Schlick approximation to the Fresnel equations."""
    return f0 + (f90 - f0) * (1.0 - u) ** 5


def Fd_Lambert():
    """Lambertian diffuse BRDF."""
    return 1.0 / math.pi


def D_Charlie(NoH, roughness):
    """Charlie/Estevez-Kulla Normal Distribution for cloth shading."""
    sin2h = max(1.0 - NoH * NoH, 0.0)
    if sin2h == 0.0:
        return 0.0
    inv_r = 1.0 / roughness
    return (2.0 + inv_r) * math.pow(sin2h, inv_r * 0.5) / (2.0 * math.pi)


def V_Neubelt(NoV, NoL):
    """Neubelt visibility function for cloth shading."""
    return 1.0 / (4.0 * (NoL + NoV - NoL * NoV) + 1e-7)
'''

CORRECTED_SAMPLING = '''\
"""Importance sampling utilities for PBR computations."""
import math


def hammersley(i, num_samples):
    """Hammersley quasi-random sequence for low-discrepancy sampling."""
    bits = i
    bits = ((bits & 0x55555555) << 1) | ((bits & 0xAAAAAAAA) >> 1)
    bits = ((bits & 0x33333333) << 2) | ((bits & 0xCCCCCCCC) >> 2)
    bits = ((bits & 0x0F0F0F0F) << 4) | ((bits & 0xF0F0F0F0) >> 4)
    bits = ((bits & 0x00FF00FF) << 8) | ((bits & 0xFF00FF00) >> 8)
    bits = ((bits & 0x0000FFFF) << 16) | ((bits & 0xFFFF0000) >> 16)
    radical_inverse = bits * 2.3283064365386963e-10
    return (i / num_samples, radical_inverse)


def importance_sample_GGX(xi_x, xi_y, alpha):
    """Sample half-vector from GGX distribution."""
    phi = 2.0 * math.pi * xi_x
    a2 = alpha * alpha
    cos_theta_sq = (1.0 - xi_y) / (1.0 + (a2 - 1.0) * xi_y)
    cos_theta = math.sqrt(max(cos_theta_sq, 0.0))
    sin_theta = math.sqrt(max(1.0 - cos_theta_sq, 0.0))
    return (sin_theta * math.cos(phi), sin_theta * math.sin(phi), cos_theta)


def importance_sample_Charlie(xi_x, xi_y, roughness):
    """Sample half-vector from Charlie distribution for cloth shading."""
    phi = 2.0 * math.pi * xi_x
    xi_y_safe = max(xi_y, 1e-10)
    sin_theta = math.pow(xi_y_safe, roughness / (2.0 * roughness + 1.0))
    cos_theta = math.sqrt(max(1.0 - sin_theta * sin_theta, 0.0))
    return (sin_theta * math.cos(phi), sin_theta * math.sin(phi), cos_theta)
'''

CORRECTED_DFG = '''\
"""DFG Lookup Table generators for split-sum IBL approximation."""
import math
from brdf import V_SmithGGXCorrelated, F_Schlick, V_Neubelt
from sampling import hammersley, importance_sample_GGX, importance_sample_Charlie


def compute_dfg(NoV, roughness, num_samples=1024):
    """Compute standard GGX DFG integration terms."""
    alpha = roughness * roughness

    V = (math.sqrt(max(1.0 - NoV * NoV, 0.0)), 0.0, NoV)
    dfg_x = 0.0
    dfg_y = 0.0

    for i in range(num_samples):
        xi_x, xi_y = hammersley(i, num_samples)
        Hx, Hy, Hz = importance_sample_GGX(xi_x, xi_y, alpha)

        VoH = max(V[0] * Hx + V[1] * Hy + V[2] * Hz, 0.0)
        Lx = 2.0 * VoH * Hx - V[0]
        Ly = 2.0 * VoH * Hy - V[1]
        Lz = 2.0 * VoH * Hz - V[2]

        NoL = max(Lz, 0.0)
        NoH = max(Hz, 0.0)
        VoH = max(V[0] * Hx + V[1] * Hy + V[2] * Hz, 0.0)

        if NoL > 0.0 and NoH > 0.0:
            vis = V_SmithGGXCorrelated(NoV, NoL, alpha)
            weight = vis * 4.0 * VoH * NoL / NoH

            Fc = F_Schlick(VoH, 0.0, 1.0)
            dfg_x += weight * (1.0 - Fc)
            dfg_y += weight * Fc

    dfg_x /= num_samples
    dfg_y /= num_samples
    return (dfg_x, dfg_y)


def compute_dfg_cloth(NoV, roughness, num_samples=1024):
    """Compute cloth DFG using Charlie distribution and Neubelt visibility."""
    V = (math.sqrt(max(1.0 - NoV * NoV, 0.0)), 0.0, NoV)
    dfg = 0.0

    for i in range(num_samples):
        xi_x, xi_y = hammersley(i, num_samples)
        Hx, Hy, Hz = importance_sample_Charlie(xi_x, xi_y, roughness)

        VoH = max(V[0] * Hx + V[1] * Hy + V[2] * Hz, 0.0)
        Lz = 2.0 * VoH * Hz - V[2]
        NoL = max(Lz, 0.0)
        NoH = max(Hz, 0.0)

        if NoL > 0.0 and NoH > 0.0:
            vis = V_Neubelt(NoV, NoL)
            weight = vis * 4.0 * VoH * NoL / NoH
            dfg += weight

    dfg /= num_samples
    return dfg


def compute_dfg_multiscatter(NoV, roughness, num_samples=1024):
    """Compute multi-scattering energy-compensated DFG with Kulla-Conty method."""
    # Step 1: Single-scatter DFG
    dfg_x, dfg_y = compute_dfg(NoV, roughness, num_samples)
    E = dfg_x + dfg_y

    # Step 2: Compute E_avg by numerical integration over view angles
    n_view = 16
    e_sum = 0.0
    inner_samples = max(num_samples // 4, 256)
    for j in range(n_view):
        mu = (j + 0.5) / n_view
        ex, ey = compute_dfg(mu, roughness, inner_samples)
        e_sum += (ex + ey) * mu
    E_avg = 2.0 * e_sum / n_view

    # Step 3: Energy compensation - DFG_ms = DFG / E
    if E > 1e-7:
        dfg_x_ms = dfg_x / E
        dfg_y_ms = dfg_y / E
    else:
        dfg_x_ms = 0.5
        dfg_y_ms = 0.5

    return (dfg_x_ms, dfg_y_ms, E_avg)
'''


def main():
    with open('/app/brdf.py', 'w') as f:
        f.write(CORRECTED_BRDF)
    print("Fixed brdf.py: D_GGX numerator, V_SmithGGX exact form, F_Schlick power; added D_Charlie, V_Neubelt")

    with open('/app/sampling.py', 'w') as f:
        f.write(CORRECTED_SAMPLING)
    print("Fixed sampling.py: importance_sample_GGX alpha^2; added importance_sample_Charlie")

    with open('/app/dfg_generator.py', 'w') as f:
        f.write(CORRECTED_DFG)
    print("Fixed dfg_generator.py: roughness remapping, weight NoL factor; added cloth DFG, multiscatter DFG")


if __name__ == '__main__':
    main()
