#!/usr/bin/env python3
"""Fix all six mathematical bugs in the PBR BRDF pipeline.

Bug 1 (brdf.py, D_GGX): Numerator uses alpha instead of alpha^2.
Bug 2 (brdf.py, V_SmithGGXCorrelated): Uses fast linear approximation
       instead of the exact height-correlated form with square roots.
Bug 3 (brdf.py, F_Schlick): Uses 4th power instead of 5th power.
Bug 4 (sampling.py, importance_sample_GGX): Uses alpha instead of
       alpha^2 in the cos_theta^2 formula.
Bug 5 (dfg_generator.py, weight): Missing NoL factor in the importance
       sampling weight after PDF cancellation.
Bug 6 (dfg_generator.py, roughness): Uses perceptual roughness directly
       instead of squaring to get linear roughness (alpha).
"""

CORRECTED_BRDF = '''\
"""PBR BRDF component functions following Filament's rendering model."""
import math


def D_GGX(NoH, alpha):
    """GGX/Trowbridge-Reitz Normal Distribution Function.

    Args:
        NoH: dot(normal, half_vector), clamped to [0, 1]
        alpha: linear roughness (already remapped from perceptual)
    Returns:
        Distribution value
    """
    a2 = alpha * alpha
    f = NoH * NoH * (a2 - 1.0) + 1.0
    return a2 / (math.pi * f * f)


def V_SmithGGXCorrelated(NoV, NoL, alpha):
    """Height-correlated Smith-GGX Visibility function.

    Args:
        NoV: dot(normal, view), clamped to [0, 1]
        NoL: dot(normal, light), clamped to [0, 1]
        alpha: linear roughness
    Returns:
        Visibility term (includes 1/(4*NoV*NoL) denominator)
    """
    a2 = alpha * alpha
    GGXV = NoL * math.sqrt(NoV * NoV * (1.0 - a2) + a2)
    GGXL = NoV * math.sqrt(NoL * NoL * (1.0 - a2) + a2)
    return 0.5 / (GGXV + GGXL + 1e-7)


def F_Schlick(u, f0, f90=1.0):
    """Schlick approximation to the Fresnel equations.

    Args:
        u: dot(light, half_vector) or dot(view, half_vector)
        f0: reflectance at normal incidence
        f90: reflectance at grazing incidence (default 1.0)
    Returns:
        Fresnel term
    """
    return f0 + (f90 - f0) * (1.0 - u) ** 5


def Fd_Lambert():
    """Lambertian diffuse BRDF."""
    return 1.0 / math.pi
'''

CORRECTED_SAMPLING = '''\
"""Importance sampling utilities for PBR computations."""
import math


def hammersley(i, num_samples):
    """Hammersley quasi-random sequence for low-discrepancy sampling.

    Returns a 2D point (x, y) in [0, 1) using the Van der Corput
    radical inverse for the second dimension.

    Args:
        i: sample index
        num_samples: total number of samples
    Returns:
        Tuple (x, y) of quasi-random numbers
    """
    bits = i
    bits = ((bits & 0x55555555) << 1) | ((bits & 0xAAAAAAAA) >> 1)
    bits = ((bits & 0x33333333) << 2) | ((bits & 0xCCCCCCCC) >> 2)
    bits = ((bits & 0x0F0F0F0F) << 4) | ((bits & 0xF0F0F0F0) >> 4)
    bits = ((bits & 0x00FF00FF) << 8) | ((bits & 0xFF00FF00) >> 8)
    bits = ((bits & 0x0000FFFF) << 16) | ((bits & 0xFFFF0000) >> 16)
    radical_inverse = bits * 2.3283064365386963e-10  # / 0x100000000
    return (i / num_samples, radical_inverse)


def importance_sample_GGX(xi_x, xi_y, alpha):
    """Sample half-vector from GGX distribution using importance sampling.

    Generates a microfacet normal (half-vector) distributed according to
    the GGX normal distribution function.

    Args:
        xi_x: first quasi-random number [0, 1)
        xi_y: second quasi-random number [0, 1)
        alpha: linear roughness
    Returns:
        Tuple (Hx, Hy, Hz) - half-vector in tangent space (N = [0,0,1])
    """
    phi = 2.0 * math.pi * xi_x
    a2 = alpha * alpha
    cos_theta_sq = (1.0 - xi_y) / (1.0 + (a2 - 1.0) * xi_y)
    cos_theta = math.sqrt(max(cos_theta_sq, 0.0))
    sin_theta = math.sqrt(max(1.0 - cos_theta_sq, 0.0))
    return (sin_theta * math.cos(phi), sin_theta * math.sin(phi), cos_theta)
'''

CORRECTED_DFG = '''\
"""DFG Lookup Table Generator for split-sum IBL approximation.

The DFG LUT stores preintegrated BRDF terms used in the split-sum
approximation for image-based lighting. Each entry (NoV, roughness)
stores two values:
  - DFG.x: base reflectance weight (coefficient of f0)
  - DFG.y: Fresnel weight (coefficient of f90)

At runtime: specular_ibl = prefilteredEnv * (f0 * DFG.x + f90 * DFG.y)
"""
import math
from brdf import V_SmithGGXCorrelated, F_Schlick
from sampling import hammersley, importance_sample_GGX


def compute_dfg(NoV, roughness, num_samples=1024):
    """Compute DFG integration terms for given view angle and roughness.

    Args:
        NoV: dot(normal, view), in (0, 1]
        roughness: perceptual roughness in [0, 1]
        num_samples: number of importance samples
    Returns:
        Tuple (dfg_x, dfg_y)
    """
    alpha = roughness * roughness

    # View vector in tangent space where N = (0, 0, 1)
    V = (math.sqrt(max(1.0 - NoV * NoV, 0.0)), 0.0, NoV)

    dfg_x = 0.0
    dfg_y = 0.0

    for i in range(num_samples):
        xi_x, xi_y = hammersley(i, num_samples)
        Hx, Hy, Hz = importance_sample_GGX(xi_x, xi_y, alpha)

        # Reflect view vector around half vector to get light vector
        VoH = max(V[0] * Hx + V[1] * Hy + V[2] * Hz, 0.0)
        Lx = 2.0 * VoH * Hx - V[0]
        Ly = 2.0 * VoH * Hy - V[1]
        Lz = 2.0 * VoH * Hz - V[2]

        NoL = max(Lz, 0.0)
        NoH = max(Hz, 0.0)
        VoH = max(V[0] * Hx + V[1] * Hy + V[2] * Hz, 0.0)

        if NoL > 0.0 and NoH > 0.0:
            vis = V_SmithGGXCorrelated(NoV, NoL, alpha)

            # Weight after PDF cancellation:
            # integrand = D * V * NoL
            # PDF = D * NoH / (4 * VoH)
            # weight = integrand / PDF = V * 4 * VoH * NoL / NoH
            weight = vis * 4.0 * VoH * NoL / NoH

            Fc = F_Schlick(VoH, 0.0, 1.0)
            dfg_x += weight * (1.0 - Fc)
            dfg_y += weight * Fc

    dfg_x /= num_samples
    dfg_y /= num_samples

    return (dfg_x, dfg_y)
'''


def main():
    with open('/app/brdf.py', 'w') as f:
        f.write(CORRECTED_BRDF)
    print("Fixed brdf.py: D_GGX numerator, V_SmithGGX exact form, F_Schlick power")

    with open('/app/sampling.py', 'w') as f:
        f.write(CORRECTED_SAMPLING)
    print("Fixed sampling.py: importance_sample_GGX alpha^2")

    with open('/app/dfg_generator.py', 'w') as f:
        f.write(CORRECTED_DFG)
    print("Fixed dfg_generator.py: roughness remapping, weight NoL factor")


if __name__ == '__main__':
    main()
