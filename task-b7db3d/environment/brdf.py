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
    return alpha / (math.pi * f * f)


def V_SmithGGXCorrelated(NoV, NoL, alpha):
    """Height-correlated Smith-GGX Visibility function.

    Args:
        NoV: dot(normal, view), clamped to [0, 1]
        NoL: dot(normal, light), clamped to [0, 1]
        alpha: linear roughness
    Returns:
        Visibility term (includes 1/(4*NoV*NoL) denominator)
    """
    a = alpha
    GGXV = NoL * (NoV * (1.0 - a) + a)
    GGXL = NoV * (NoL * (1.0 - a) + a)
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
    return f0 + (f90 - f0) * (1.0 - u) ** 4


def Fd_Lambert():
    """Lambertian diffuse BRDF."""
    return 1.0 / math.pi


def D_Charlie(NoH, roughness):
    """Charlie/Estevez-Kulla Normal Distribution for cloth shading.

    Implements the sheen NDF from "Production Friendly Microfacet Sheen BRDF"
    (Estevez and Kulla, 2017).

    Args:
        NoH: dot(normal, half_vector), clamped to [0, 1]
        roughness: cloth roughness parameter in (0, 1]
    Returns:
        Distribution value
    """
    # TODO: Implement Charlie NDF
    # See spec.md Section 9 for the formula
    raise NotImplementedError("D_Charlie not implemented")


def V_Neubelt(NoV, NoL):
    """Neubelt visibility function for cloth shading.

    A simple, cheap visibility function designed for cloth/fabric materials.

    Args:
        NoV: dot(normal, view), clamped to [0, 1]
        NoL: dot(normal, light), clamped to [0, 1]
    Returns:
        Visibility term
    """
    # TODO: Implement Neubelt visibility
    # See spec.md Section 10 for the formula
    raise NotImplementedError("V_Neubelt not implemented")
