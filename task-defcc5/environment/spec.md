# Rectangular Prism Gravity Forward Model — Mathematical Specification

## Overview

This document specifies the gravitational forward model for a uniform-density
rectangular prism (right rectangular parallelepiped) following the formulation of
Nagy et al. (2000, 2002) with the numerically stable auxiliary functions of
Fukushima (2020).

The model computes 10 gravitational field quantities at an observation point
**p** = (e_p, n_p, u_p) due to a prism with boundaries
[e₁, e₂] × [n₁, n₂] × [u₁, u₂] and uniform density ρ.

## Coordinate system

- **easting (e)**: positive east
- **northing (n)**: positive north
- **upward (u)**: positive up

All coordinates and lengths are in SI (meters). Density is in kg/m³.

## Gravitational constant

G = 6.6743 × 10⁻¹¹ m³ kg⁻¹ s⁻²

## 1  Shifted coordinates

For each prism boundary vertex (eᵢ, nⱼ, uₖ) with i,j,k ∈ {1,2}, the shifted
coordinates relative to the observation point are:

    Eᵢ = eᵢ − e_p
    Nⱼ = nⱼ − n_p
    Uₖ = uₖ − u_p
    Rᵢⱼₖ = √(Eᵢ² + Nⱼ² + Uₖ²)

## 2  Auxiliary functions

### 2.1  safe-arctan(y, x)

    safe_atan2(y, x) =
        arctan(y/x)   if x ≠ 0
        π/2            if x = 0 and y > 0
       −π/2            if x = 0 and y < 0
        0              if x = 0 and y = 0

### 2.2  safe-log(x, y, z, r)

Evaluates ln(x + r) with four branches for numerical stability:

    safe_log(x, y, z, r) =
        0                         if r = 0
        ln(x + r)                 if x ≥ 0
        ln((y² + z²) / (r − x))  if x < 0 and (y ≠ 0 or z ≠ 0)
       −ln(−2x)                   if x < 0 and y = 0 and z = 0

Here **x** is the primary shifted coordinate appearing in the log, **y** and
**z** are the other two shifted coordinates, and **r** = √(x² + y² + z²).

The check for the fourth branch (r = |x|) is performed by testing y = 0 and
z = 0, which avoids floating-point issues when |x| ≫ |y|, |z|.

## 3  Kernel functions

All kernel functions take shifted coordinates (E, N, U) and the radius R.

### 3.1  Potential kernel

    k_V(E, N, U, R) =
          E·N · safe_log(U, E, N, R)
        + N·U · safe_log(E, N, U, R)
        + E·U · safe_log(N, U, E, R)
        − (E²/2) · safe_atan2(N·U, E·R)
        − (N²/2) · safe_atan2(E·U, N·R)
        − (U²/2) · safe_atan2(E·N, U·R)

### 3.2  Gradient kernels (first-order)

These give the components of gravitational acceleration. Each includes a leading
minus sign so that the vertex-summation formula below yields ∂V/∂coord directly.

    k_e(E, N, U, R) = −[ N · safe_log(U, E, N, R)
                        + U · safe_log(N, U, E, R)
                        − E · safe_atan2(N·U, E·R) ]

    k_n(E, N, U, R) = −[ U · safe_log(E, N, U, R)
                        + E · safe_log(U, E, N, R)
                        − N · safe_atan2(E·U, N·R) ]

    k_u(E, N, U, R) = −[ E · safe_log(N, U, E, R)
                        + N · safe_log(E, N, U, R)
                        − U · safe_atan2(E·N, U·R) ]

### 3.3  Tensor kernels (second-order)

Diagonal components:

    k_ee(E, N, U, R) = −safe_atan2(N·U, E·R)     [NaN if R = 0]
    k_nn(E, N, U, R) = −safe_atan2(E·U, N·R)     [NaN if R = 0]
    k_uu(E, N, U, R) = −safe_atan2(E·N, U·R)     [NaN if R = 0]

Off-diagonal components:

    k_en(E, N, U, R) = safe_log(U, E, N, R)       [NaN if R = 0]
    k_eu(E, N, U, R) = safe_log(N, E, U, R)       [NaN if R = 0]
    k_nu(E, N, U, R) = safe_log(E, N, U, R)       [NaN if R = 0]

Note the argument order in each safe_log call for the off-diagonal kernels: the
first argument identifies which coordinate appears in the log expression.

## 4  Vertex summation (evaluate-kernel)

For any kernel function k, the contribution from a single prism is obtained by
evaluating k on all 8 vertices with alternating signs:

    result = Σᵢ Σⱼ Σₖ (−1)^(i+j+k) · k(Eᵢ, Nⱼ, Uₖ, Rᵢⱼₖ)

where:
- i = 0 → Eᵢ = e₂ − e_p  (east / upper bound)
- i = 1 → Eᵢ = e₁ − e_p  (west / lower bound)
- j = 0 → Nⱼ = n₂ − n_p  (north / upper bound)
- j = 1 → Nⱼ = n₁ − n_p  (south / lower bound)
- k = 0 → Uₖ = u₂ − u_p  (top / upper bound)
- k = 1 → Uₖ = u₁ − u_p  (bottom / lower bound)

This is the numerical evaluation of the triple definite-integral formula using
Green's theorem.

## 5  Full field computation

    field(p) = G · ρ · evaluate_kernel(k_field)

where k_field is the appropriate kernel from §3. The field names and their SI
units are:

| field name  | kernel   | SI unit |
|-------------|----------|---------|
| potential   | k_V      | m²/s²   |
| g_e         | k_e      | m/s²    |
| g_n         | k_n      | m/s²    |
| g_u         | k_u      | m/s²    |
| g_ee        | k_ee     | 1/s²    |
| g_nn        | k_nn     | 1/s²    |
| g_uu        | k_uu     | 1/s²    |
| g_en        | k_en     | 1/s²    |
| g_eu        | k_eu     | 1/s²    |
| g_nu        | k_nu     | 1/s²    |

## 6  Physical constraints (for verification)

1. **Laplace's equation**: At any point outside the prism,
   g_ee + g_nn + g_uu = 0.

2. **Symmetry**: For a prism centered at the origin, the potential at six
   equidistant points along the three Cartesian axes must be equal.

3. **Bouguer slab**: As the horizontal extent of a flat prism → ∞, the upward
   acceleration g_u at the top surface converges to −2πGρh, where h is the
   slab thickness.

4. **Finite-difference consistency**: g_e ≈ [V(e+δ) − V(e−δ)] / (2δ), and
   similarly for other gradient and tensor components.

5. **Tensor singularity**: Tensor components are undefined (NaN) when the
   observation point coincides with a prism vertex (R = 0 for one vertex).

## References

- Nagy, D., Papp, G., & Benedek, J. (2000). The gravitational potential and
  its derivatives for the prism. Journal of Geodesy, 74, 552–560.
- Nagy, D., Papp, G., & Benedek, J. (2002). Corrections to "The gravitational
  potential and its derivatives for the prism." Journal of Geodesy, 76, 475.
- Fukushima, T. (2020). Speed and accuracy improvements in standard algorithm
  for prismatic gravitational field. Geophysical Journal International, 222,
  1898–1908.
