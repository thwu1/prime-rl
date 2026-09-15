#!/usr/bin/env python3

"""Quasi-random sampling functions for Monte Carlo BRDF integration."""

import math

PI = math.pi


def radical_inverse(bits):
    """Van der Corput radical inverse in base 2 (32-bit)."""
    bits = int(bits) & 0xFFFFFFFF
    bits = ((bits << 16) | (bits >> 16)) & 0xFFFFFFFF
    bits = (((bits & 0x55555555) << 1) | ((bits & 0xAAAAAAAA) >> 1)) & 0xFFFFFFFF
    bits = (((bits & 0x33333333) << 2) | ((bits & 0xCCCCCCCC) >> 2)) & 0xFFFFFFFF
    bits = (((bits & 0x0F0F0F0F) << 4) | ((bits & 0xF0F0F0F0) >> 4)) & 0xFFFFFFFF
    bits = (((bits & 0x00FF00FF) << 8) | ((bits & 0xFF00FF00) >> 8)) & 0xFFFFFFFF
    return bits * 2.3283064365386963e-10


def hammersley(i, inv_n):
    """Return the i-th 2D Hammersley point on [0,1)^2."""
    return (i * inv_n, radical_inverse(i))


def importance_sample_ggx(u, a):
    """
    Importance-sample the GGX (Trowbridge-Reitz) NDF in tangent space.
    a = linear roughness (alpha).
    Returns half-vector H = (x, y, z) with z = cos(theta).
    PDF = D_GGX(H) * cos(theta).
    """
    phi = 2.0 * PI * u[0]
    # (a+1)(a-1) = a^2-1 for better floating-point accuracy near a~0
    cos_theta_sq = (1.0 - u[1]) / (1.0 + (a + 1.0) * ((a - 1.0) * u[1]))
    cos_theta_sq = max(0.0, min(1.0, cos_theta_sq))
    cos_theta = math.sqrt(cos_theta_sq)
    sin_theta = math.sqrt(max(0.0, 1.0 - cos_theta_sq))
    return (sin_theta * math.cos(phi), sin_theta * math.sin(phi), cos_theta)


def hemisphere_uniform_sample(u):
    """
    Uniform hemisphere sampling.
    PDF = 1 / (2*pi).
    """
    phi = 2.0 * PI * u[0]
    cos_theta = 1.0 - u[1]
    sin_theta = math.sqrt(max(0.0, 1.0 - cos_theta * cos_theta))
    return (sin_theta * math.cos(phi), sin_theta * math.sin(phi), cos_theta)
