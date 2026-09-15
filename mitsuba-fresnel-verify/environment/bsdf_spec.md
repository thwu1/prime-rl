# Beckmann Microfacet BSDF — Mathematical Reference

All directions are in the local shading frame where the surface normal is **n** = (0, 0, 1).
Directions ωi and ωo both point away from the surface into the upper hemisphere.
θ denotes the polar angle from **n**: cos θ = ω_z.

## 1. Fresnel Equations

### Dielectric (Unpolarized)

Given cos θ_i and refractive indices n₁ (incident), n₂ (transmitted):

    sin²θ_t = (n₁/n₂)² · (1 − cos²θ_i)

If sin²θ_t ≥ 1: total internal reflection, R = 1.

Otherwise cos θ_t = √(1 − sin²θ_t) and:

    r_s = (n₁·cos θ_i − n₂·cos θ_t) / (n₁·cos θ_i + n₂·cos θ_t)
    r_p = (n₂·cos θ_i − n₁·cos θ_t) / (n₂·cos θ_i + n₁·cos θ_t)
    R = ½·(r_s² + r_p²)

### Conductor

Given cos θ_i, real part η and extinction coefficient k of the complex IOR:

    cos²θ = cos²θ_i,   sin²θ = 1 − cos²θ
    t₀ = η² − k² − sin²θ
    a²+b² = √(t₀² + 4·η²·k²)
    a = √(max(0, ½·(a²+b² + t₀)))

    r_s = (a²+b² + cos²θ − 2·a·cos θ_i) / (a²+b² + cos²θ + 2·a·cos θ_i)
    r_p = r_s · (cos²θ·(a²+b²) + sin⁴θ − 2·a·cos θ_i·sin²θ) /
                 (cos²θ·(a²+b²) + sin⁴θ + 2·a·cos θ_i·sin²θ)
    R = ½·(r_s + r_p)

## 2. Beckmann Normal Distribution Function

    D(m) = exp(−tan²θ_m / α²) / (π · α² · cos⁴θ_m)

where θ_m is the polar angle of microfacet normal m, and α is the roughness parameter.

## 3. Smith Masking Function (Beckmann)

For direction v with polar angle θ_v, define a = 1/(α · tan θ_v).

    G₁(v) = 2 / (1 + erf(a) + exp(−a²) / (a·√π))

The separable masking-shadowing approximation:

    G(ωi, ωo) = G₁(ωi) · G₁(ωo)

## 4. Microfacet Reflection BSDF (Cook-Torrance)

Half-vector: **h** = normalize(ωi + ωo)

    f_r(ωi, ωo) = F(ωi · **h**) · D(**h**) · G(ωi, ωo) / (4 · cos θ_i · cos θ_o)

The cosine-weighted evaluation is:

    f_r · cos θ_o = F · D · G / (4 · cos θ_i)

## 5. MC Estimation of Directional-Hemispherical Reflectance

    ρ(ωi) = ∫ f_r(ωi, ωo) · cos θ_o · dωo

Estimate via importance sampling of the Beckmann NDF:

1. Sample microfacet normal m from p(m) = D(m)·cos θ_m using the inverse CDF:
   tan²θ_m = −α²·ln(1 − ξ₁),   φ_m = 2π·ξ₂
2. Compute ωo = 2(ωi · m)m − ωi   (reflection about m)
3. Reject if ωo · **n** ≤ 0
4. Derive the MC weight from the BSDF, the sampling PDF p(ωo), and the
   half-vector-to-reflection Jacobian |∂ωh/∂ωo| = 1/(4|ωi · m|)
