# Sedov Blast Wave Problem — Mathematical Specification

This document provides the mathematical formulation needed to implement
a solver for the Sedov-Taylor self-similar blast wave problem, following
Kamm & Timmes (2007), "Multiphysics simulations: Challenges and opportunities."

## 1. Problem Description

A point explosion deposits energy E₀ at the origin at time t = 0 in a gas
with initial density profile ρ₀ r^{-ω} and zero pressure. The resulting
strong shock wave expands self-similarly.

## 2. Parameters

| Symbol | Name       | Description                                              | Default |
|--------|------------|----------------------------------------------------------|---------|
| j      | geometry   | 1=planar, 2=cylindrical, 3=spherical                     | 3       |
| γ      | gamma      | specific heat ratio c_p / c_v                            | 1.4     |
| ρ₀     | rho0       | reference density                                        | 1.0     |
| ω      | omega      | power-law exponent for initial density ρ = ρ₀ r^{-ω}    | 0.0     |
| E₀     | eblast     | total deposited energy                                   | 0.851072|

Constraints: j ∈ {1,2,3}, γ > 1, ρ₀ > 0, E₀ > 0, 0 ≤ ω < j.

## 3. Frequently Used Constants

    γ₋₁ = γ - 1
    γ₊₁ = γ + 1
    G   = γ₊₁ / γ₋₁                    (density compression ratio)
    X   = j + 2 - ω                     (geometry+2-omega)

## 4. Key Velocity Ratios

    v₂  = 4 / (X · γ₊₁)               (shock-jump similarity variable)
    v*  = 2 / (γ₋₁ · j + 2)            (critical value)
    v₀  = 2 / (X · γ)                   (post-shock origin)

## 5. Solution Type Classification

Compare v₂ to v* (using tolerance ~1e-4):
- |v₂ - v*| ≤ tol  →  "singular"
- v₂ < v* - tol    →  "standard"
- v₂ > v* + tol    →  "vacuum"

## 6. Denominators and Special Singularities

    denom₂ = 2·γ₋₁ + j - γ·ω
    denom₃ = j·(2 - γ) - ω

If |denom₂| ≤ tol → special singularity "omega2", set denom₂ = 1e-8.
If |denom₃| ≤ tol → special singularity "omega3", set denom₃ = 1e-8.
Otherwise → "none".

## 7. Exponents (Kamm equations 42–47)

    a₀ = 2 / X
    a₂ = -γ₋₁ / denom₂
    a₁ = (X·γ / (2 + j·γ₋₁)) · ((2·(j·(2-γ) - ω)) / (γ·X²) - a₂)
    a₃ = (j - ω) / denom₂
    a₄ = X·(j - ω)·a₁ / denom₃
    a₅ = (ω·γ₊₁ - 2·j) / denom₃

## 8. Intermediate Constants (Kamm equations 33–37)

    A = X·γ₊₁ / 4
    B = G = γ₊₁ / γ₋₁
    C = X·γ / 2
    D = X·γ₊₁ / (X·γ₊₁ - 2·(2 + j·γ₋₁))
    E = (2 + j·γ₋₁) / 2

## 9. Sedov Functions — Standard Case (equations 38–41)

Given the similarity variable v, define:

    x₁ = A·v                       (Kamm's "F")
    x₂ = B·max(C·v - 1, 1e-30)    (avoid division by zero)
    x₃ = D·(1 - E·v)
    x₄ = max(B·(1 - X·v/2), 1e-12)

Then the Sedov functions are:

    λ(v)  = x₁^{-a₀} · x₂^{-a₂} · x₃^{-a₁}
    dλ/dv = -(a₀·A/x₁ + a₂·B·C/x₂ + a₁·(-D·E)/x₃) · λ

    f(v) = x₁ · λ(v)                                        (velocity function V)
    g(v) = x₁^{a₀·ω} · x₂^{a₃+a₂·ω} · x₃^{a₄+a₁·ω} · x₄^{a₅}  (density function D)
    h(v) = x₁^{a₀·j} · x₃^{a₄+a₁·(ω-2)} · x₄^{1+a₅}      (pressure function P)

## 10. Sedov Functions — Special Singularity: omega2 (equations 20–22)

When denom₂ ≈ 0, replace the standard formulas with:

    β₀  = 1 / (2·E)
    pp₁ = γ₋₁ · β₀
    c₆  = γ₊₁ / 2
    c₂  = c₆ / γ
    y   = 1 / (x₁ - c₂)
    z   = (1 - x₁) · y
    pp₂ = γ₊₁ · β₀ · z
    dpp₂/dv = -γ₊₁ · β₀ · A · y · (1 + z)
    pp₃ = (4 - j - 2·γ) · β₀
    pp₄ = -j · γ · β₀

    λ(v)  = x₁^{-a₀} · x₂^{pp₁} · exp(pp₂)
    dλ/dv = (-a₀·A/x₁ + pp₁·B·C/x₂ + dpp₂/dv) · λ
    f(v)  = x₁ · λ
    g(v)  = x₁^{a₀·ω} · x₂^{pp₃} · x₄^{a₅} · exp(-2·pp₂)
    h(v)  = x₁^{a₀·j} · x₂^{pp₄} · x₄^{1+a₅}

## 11. Sedov Functions — Special Singularity: omega3 (equations 23–25)

When denom₃ ≈ 0:

    β₀  = 1 / (2·E)
    pp₁ = a₃ + ω·a₂
    pp₂ = 1 - 4·β₀
    c₆  = γ₊₁ / 2
    pp₃ = -j·γ·γ₊₁·β₀·(1 - x₁) / (c₆ - x₁)
    pp₄ = 2·(j·γ₋₁ - γ)·β₀

    λ(v)  = x₁^{-a₀} · x₂^{-a₂} · x₄^{-a₁}
    dλ/dv = -(a₀·A/x₁ + a₂·B·C/x₂ + a₁·(-B·X/2)/x₄) · λ
    f(v)  = x₁ · λ
    g(v)  = x₁^{a₀·ω} · x₂^{pp₁} · x₄^{pp₂} · exp(pp₃)
    h(v)  = x₁^{a₀·j} · x₄^{pp₄} · exp(pp₃)

## 12. Singular Solution Type (equations 80–81, 85)

When solution_type == "singular", all functions have closed forms:

    λ(r)  = r / r₂
    f     = λ
    g     = λ^{j-2}
    h     = λ^j

Energy integrals:

    eval₂ = γ₊₁ / (j · (γ₋₁·j + 2)²)
    eval₁ = 2 / γ₋₁ · eval₂
    α     = G · 2^j / (j · (γ₋₁·j + 2)²)
    if j ≠ 1:  α *= π

## 13. Vacuum Solution Type

For the vacuum case, there exists a vacuum boundary at radius r_v:
- Compute λ_v = λ(v_v) where v_v = 2/X
- r_v = λ_v · r₂
- For r < r_v: density=0, velocity=0, pressure=0

Integration bounds for vacuum: v ranges from v₂ to v_v (reversed from standard).

## 14. Energy Integrals (non-singular case)

    efun₁(v) = (dλ/dv) · λ^{j+1} · G · g(v) · v²
    efun₂(v) = (dλ/dv) · λ^{j-1} · h(v) · z

where z = 8 / (X² · γ₊₁).

For standard case, integrate from v₀ to v₂.
For vacuum case, integrate from v_v to v₂.

    eval₁ = ∫ efun₁(v) dv
    eval₂ = ∫ efun₂(v) dv

Use scipy.integrate.quad with epsabs ≈ 1e-12.

## 15. Alpha Constant

    For j = 1:  α = eval₁/2 + eval₂/γ₋₁
    For j > 1:  α = (j-1)·π · (eval₁ + 2·eval₂/γ₋₁)

## 16. Shock Position and Jump Conditions

At time t:

    r₂ = (E₀ / (α·ρ₀))^{1/X} · t^{2/X}            (shock position)
    ρ₁ = ρ₀ · r₂^{-ω}                               (pre-shock density)
    u_s = (2/X) · r₂/t                               (shock speed)
    u₂  = 2·u_s / γ₊₁                                (post-shock velocity)
    ρ₂  = G · ρ₁                                      (post-shock density)
    p₂  = 2·ρ₁·u_s² / γ₊₁                            (post-shock pressure)

## 17. Mapping to Physical Variables

For each spatial position r at time t:

1. If r > r₂: pre-shock conditions (ρ₀·r^{-ω}, u=0, p=0)
2. If r ≤ r₂:
   a. Compute λ_want = r / r₂
   b. Find v such that λ(v) = λ_want by minimizing (λ(v) - λ_want)²
      - Standard: search v ∈ [v₀, v₂]
      - Vacuum: search v ∈ [v₂, v_v]
   c. Compute f(v), g(v), h(v) from Sedov functions
   d. Physical variables:
      - density = ρ₂ · g
      - velocity = u₂ · f
      - pressure = p₂ · h
      - specific_internal_energy = p / (γ₋₁ · ρ)     (if ρ > 0)
      - sound_speed = √(γ · p / ρ)                    (if ρ > 0)

## 18. Implementation Notes

The solver should evaluate on a fine internal grid (e.g., 3001 points from
max(r) down to 0), then interpolate back to the requested r values. This is
necessary because the v → λ mapping via optimization can lose precision at
very small r (near the origin). When the optimized v stops changing between
successive grid points (|Δv| < tolerance ~1e-8), stop the sweep and add
an explicit origin point. Use scipy.interpolate.interp1d for the final mapping.

Return an ExactSolution with fields:
    position, density, pressure, specific_internal_energy, velocity, sound_speed

Return NaN arrays when t ≤ 0.

---

# Noh Implosion Problem — Mathematical Specification

## 19. Problem Description

A gas with uniform density ρ₀ and inward radial velocity u₀ < 0 converges
toward the origin. An outward-propagating shock forms at r = 0 at t = 0.

## 20. Parameters

| Symbol | Name     | Description                              | Default   |
|--------|----------|------------------------------------------|-----------|
| j      | geometry | 1=planar, 2=cylindrical, 3=spherical     | 3         |
| γ      | gamma    | specific heat ratio                      | 5/3       |
| u₀     | u0       | incident velocity (must be negative)     | -1.0      |
| ρ₀     | rho0     | initial density                          | 1.0       |

Constraints: j ∈ {1,2,3}, γ > 1, u₀ < 0, ρ₀ > 0.

## 21. Shock Position

    r_shock(t) = |u₀| · t · (γ - 1) / 2

## 22. Post-Shock Region (r < r_shock)

The post-shock values are spatially uniform (constant behind the shock):

    G = (γ + 1) / (γ - 1)                              (compression ratio)

    density  = ρ₀ · G^j
    velocity = 0
    pressure = ρ₀ · u₀² · G^{j-1} · (γ + 1) / 2
    SIE      = u₀² / 2
    sound_speed = √(γ · pressure / density)

**Important**: The pressure formula above is the general form valid for all γ.
A simplified formula using numerical constants (like 4^j/3) only works for
γ = 5/3 and must NOT be used.

## 23. Pre-Shock Region (r > r_shock)

    density  = ρ₀ · (1 + |u₀| · t / r)^{j-1}
    velocity = u₀
    pressure = 0
    SIE      = 0
    sound_speed = 0

Note: For planar geometry (j=1), the pre-shock density is simply ρ₀.

## 24. Edge Cases

- t ≤ 0: return NaN arrays for all fields
- r = 0: always inside the shock for t > 0; use post-shock values
- Guard against division by zero in the pre-shock density formula at r = 0
  by using max(r, ε) with a small ε.

## 25. API Conformance

The solver must subclass ExactSolver from base.py and implement _run(self, r, t).
Return an ExactSolution with field names:
    position, density, pressure, specific_internal_energy, velocity, sound_speed

---

# Verification Framework — Requirements

## 26. Overview

Create a verification framework at `/app/verify.py` that performs three
analyses and writes all results to `/app/results.json`.

## 27. Quadrature Comparison

Compare three integration methods for computing the Sedov α constant
(spherical geometry, γ = 1.4, ω = 0):

1. **scipy.integrate.quad** — adaptive quadrature (already used internally by the Sedov solver)
2. **scipy.integrate.fixed_quad** with n = 15 — fixed-order Gaussian quadrature
3. **scipy.integrate.fixed_quad** with n = 40 — higher-order fixed Gaussian quadrature

**Important**: `fixed_quad` passes an array of quadrature nodes to the integrand
function, unlike `quad` which calls the function with individual scalars.
The Sedov solver's energy integrands (efun01, efun02) use Python's built-in
`max()` which does not accept arrays. You must wrap or vectorize the
integrands before passing them to `fixed_quad`.

For each method, compute eval₁ and eval₂, then α using the formula from §15.
Report all three α values and identify which method achieves closest agreement
with the reference value α = 0.851060.

## 28. Cross-Validation

For each combination of geometry ∈ {1, 2, 3} and γ ∈ {1.4, 5/3}:

1. Create a Noh solver and evaluate inside the shock to obtain the computed
   post-shock density.
2. Compute the expected post-shock density analytically: ρ₀ · G^j.
3. Create a Sedov solver and read the compression ratio G = (γ+1)/(γ-1)
   from the solver's attributes.
4. Report the analytical compression ratio, the Sedov compression ratio,
   the Noh computed density, the expected density, and the relative error.

## 29. Rankine-Hugoniot Verification

For the Sedov solver (spherical, γ = 1.4, ω = 0, E₀ = 0.851072):

1. Evaluate the physical solution on a fine grid and find the point
   closest to the shock position r₂.
2. Compare the numerical density, velocity, and pressure at the shock
   against the exact Rankine-Hugoniot values:
   - ρ₂ = ρ₀ · (γ+1)/(γ-1)
   - u₂ = 2·u_s/(γ+1)
   - p₂ = 2·ρ₀·u_s²/(γ+1)
3. Report relative errors for each quantity.

## 30. Output Format

Write results to `/app/results.json` with this structure:

```json
{
  "quadrature_comparison": {
    "quad_alpha": <float>,
    "fixed_quad_n15_alpha": <float>,
    "fixed_quad_n40_alpha": <float>,
    "reference_alpha": 0.851060,
    "quad_error": <float>,
    "fq15_error": <float>,
    "fq40_error": <float>,
    "best_method": "<string>"
  },
  "cross_validation": {
    "<geometry>_<gamma>": {
      "analytical_ratio": <float>,
      "sedov_compression": <float>,
      "noh_postshock_density": <float>,
      "noh_expected_density": <float>,
      "noh_density_error": <float>
    }
  },
  "rankine_hugoniot": {
    "shock_position": <float>,
    "density_at_shock": <float>,
    "density_exact": <float>,
    "density_rel_error": <float>,
    "velocity_at_shock": <float>,
    "velocity_exact": <float>,
    "velocity_rel_error": <float>,
    "pressure_at_shock": <float>,
    "pressure_exact": <float>,
    "pressure_rel_error": <float>
  }
}
```

Keys in cross_validation use the format `<geoname>_<gammaname>` where
geoname ∈ {planar, cylindrical, spherical} and gammaname ∈ {gamma_1_4, gamma_5_3}.
