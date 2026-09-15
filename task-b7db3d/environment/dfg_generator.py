"""DFG Lookup Table generators for split-sum IBL approximation.

The DFG LUT stores preintegrated BRDF terms used in the split-sum
approximation for image-based lighting. Three variants are supported:

Standard GGX (2 channels):
  - DFG.x: base reflectance weight (coefficient of f0)
  - DFG.y: Fresnel weight (coefficient of f90)

Cloth / Sheen (1 channel):
  - Directional albedo using Charlie NDF + Neubelt visibility

Multi-scatter (2 channels + E_avg):
  - Energy-compensated GGX DFG values using Kulla-Conty method
"""
import math
from brdf import V_SmithGGXCorrelated, F_Schlick, V_Neubelt
from sampling import hammersley, importance_sample_GGX, importance_sample_Charlie


def compute_dfg(NoV, roughness, num_samples=1024):
    """Compute standard GGX DFG integration terms.

    Args:
        NoV: dot(normal, view), in (0, 1]
        roughness: perceptual roughness in [0, 1]
        num_samples: number of importance samples
    Returns:
        Tuple (dfg_x, dfg_y)
    """
    alpha = roughness

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

            # The GGX importance sampling PDF cancels with D in the
            # integrand, leaving the visibility and geometric terms
            weight = vis * 4.0 * VoH / NoH

            Fc = F_Schlick(VoH, 0.0, 1.0)
            dfg_x += weight * (1.0 - Fc)
            dfg_y += weight * Fc

    dfg_x /= num_samples
    dfg_y /= num_samples

    return (dfg_x, dfg_y)


def compute_dfg_cloth(NoV, roughness, num_samples=1024):
    """Compute cloth/sheen DFG using Charlie distribution and Neubelt visibility.

    The cloth model returns a single scalar directional albedo (not two
    channels), since cloth shading does not use a Fresnel decomposition.

    Args:
        NoV: dot(normal, view), in (0, 1]
        roughness: cloth roughness in (0, 1]
        num_samples: number of importance samples
    Returns:
        Single float: cloth DFG directional albedo
    """
    # TODO: Implement cloth DFG integration
    # See spec.md Section 12 for the algorithm
    raise NotImplementedError("compute_dfg_cloth not implemented")


def compute_dfg_multiscatter(NoV, roughness, num_samples=1024):
    """Compute multi-scattering energy-compensated GGX DFG values.

    Uses the Kulla-Conty (2017) method to add back energy lost to multiple
    bounces in the standard single-scatter BRDF. Requires computing the
    hemisphere-averaged directional albedo E_avg.

    Args:
        NoV: dot(normal, view), in (0, 1]
        roughness: perceptual roughness in [0, 1]
        num_samples: number of importance samples
    Returns:
        Tuple (dfg_x_ms, dfg_y_ms, E_avg) where E_avg is the
        hemisphere-averaged single-scatter energy
    """
    # TODO: Implement multi-scattering DFG with Kulla-Conty compensation
    # See spec.md Section 13 for the method
    raise NotImplementedError("compute_dfg_multiscatter not implemented")
