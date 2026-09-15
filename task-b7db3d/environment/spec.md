# PBR BRDF Mathematical Specification

## Roughness Parameterization

All BRDF functions take linear roughness alpha as input.
The mapping from perceptual roughness r to linear alpha:

    alpha = r^2

## GGX Normal Distribution Function

    D_GGX(NoH, alpha) = alpha^2 / (pi * f^2)

where:

    f = NoH^2 * (alpha^2 - 1) + 1

Note: The numerator uses alpha^2 (alpha squared), not alpha.

## Height-Correlated Smith-GGX Visibility

    V(NoV, NoL, alpha) = 0.5 / (GGXV + GGXL)

where:

    GGXV = NoL * sqrt(NoV^2 * (1 - alpha^2) + alpha^2)
    GGXL = NoV * sqrt(NoL^2 * (1 - alpha^2) + alpha^2)

This is the exact form using square roots. The fast linear
approximation (GGXV ~ NoL * (NoV * (1 - alpha) + alpha)) is NOT
equivalent and must not be used for precomputation.

## Schlick Fresnel Approximation

    F(VoH, f0) = f0 + (1 - f0) * (1 - VoH)^5

The exponent is exactly 5 (Schlick's original derivation).

## Charlie NDF (Cloth/Sheen)

    D_Charlie(NoH, r) = (2 + 1/r) * sin2h^(1/(2r)) / (2*pi)

where sin2h = 1 - NoH^2, and r is the roughness parameter.
The exponent on sin2h is 1/(2r), equivalently inv_r * 0.5.

## Neubelt Visibility (Cloth)

    V_Neubelt(NoV, NoL) = 1 / (4 * (NoL + NoV - NoL * NoV))

## GGX Importance Sampling

Given uniform xi_x, xi_y in [0, 1):

    cos^2(theta) = (1 - xi_y) / (1 + (alpha^2 - 1) * xi_y)
    phi = 2*pi * xi_x
    H = (sin(theta)*cos(phi), sin(theta)*sin(phi), cos(theta))

The CDF inversion uses alpha^2 (not alpha) in the denominator.

## Charlie Importance Sampling

    sin(theta) = xi_y^(r / (2*r + 1))
    cos(theta) = sqrt(1 - sin^2(theta))
    phi = 2*pi * xi_x

## Cosine-Weighted Hemisphere Sampling

    sin(theta) = sqrt(xi_y)
    cos(theta) = sqrt(1 - xi_y)
    phi = 2*pi * xi_x

    PDF = cos(theta) / pi = NoH / pi

## Uniform Hemisphere Sampling

    cos(theta) = xi_y
    sin(theta) = sqrt(1 - cos^2(theta))
    phi = 2*pi * xi_x

    PDF = 1 / (2*pi)

## DFG Integration

The DFG integral precomputes the split-sum BRDF response:

    V = (sqrt(1 - NoV^2), 0, NoV)   in tangent space
    H = sampled half-vector
    L = 2*(V.H)*H - V               reflection of V around H

Hammersley sequence: xi = (i/N, radical_inverse(i))

### GGX IS Weight

The GGX importance sampling PDF is D * NoH. After PDF cancellation:

    weight = V_SmithGGX(NoV, NoL, alpha) * 4 * VoH * NoL / NoH

### Cosine Weight

PDF = NoH / pi. D does not cancel:

    weight = D_GGX(NoH, alpha) * V_SmithGGX(NoV, NoL, alpha) * 4 * VoH * NoL * pi / NoH

### Uniform Weight

PDF = 1 / (2*pi). Nothing cancels:

    weight = D_GGX(NoH, alpha) * V_SmithGGX(NoV, NoL, alpha) * 4 * VoH * NoL * 2*pi

### Fresnel Split

For each valid sample (NoL > 0, NoH > 0):

    Fc = (1 - VoH)^5
    DFG.x += weight * (1 - Fc) / N
    DFG.y += weight * Fc / N

### Cloth Integration

Uses Charlie IS with Neubelt visibility (single scalar output):

    weight = V_Neubelt(NoV, NoL) * 4 * VoH * NoL / NoH
    cloth_DFG = sum(weight) / N
