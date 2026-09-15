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
    cos_theta_sq = (1.0 - xi_y) / (1.0 + (alpha - 1.0) * xi_y)
    cos_theta = math.sqrt(max(cos_theta_sq, 0.0))
    sin_theta = math.sqrt(max(1.0 - cos_theta_sq, 0.0))
    return (sin_theta * math.cos(phi), sin_theta * math.sin(phi), cos_theta)


def importance_sample_Charlie(xi_x, xi_y, roughness):
    """Sample half-vector from Charlie distribution for cloth shading.

    Generates a microfacet normal distributed according to the Charlie
    (Estevez-Kulla sheen) NDF.

    Args:
        xi_x: first quasi-random number [0, 1)
        xi_y: second quasi-random number [0, 1)
        roughness: cloth roughness parameter in (0, 1]
    Returns:
        Tuple (Hx, Hy, Hz) - half-vector in tangent space (N = [0,0,1])
    """
    # TODO: Implement Charlie importance sampling
    # See spec.md Section 11 for the formula
    raise NotImplementedError("importance_sample_Charlie not implemented")
