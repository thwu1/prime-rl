# PBR DFG LUT Reference

This document describes the mathematical formulations needed to generate the DFG lookup table for Image-Based Lighting (IBL) in a Physically Based Rendering pipeline.

## 1. Overview

In the split-sum approximation for IBL, the specular contribution is decomposed as:

    L_out ≈ [f₀·DFG₁ + f₉₀·DFG₂] × LD(n, α)

where `f₀` is the Fresnel reflectance at normal incidence, `f₉₀` is reflectance at grazing angle, and `LD` is the pre-filtered environment radiance. The terms `DFG₁` and `DFG₂` depend only on the view angle `cos(θ) = n·v` and roughness, making them suitable for pre-computation into a 2D lookup table.

For the multiscatter variant (which assumes f₉₀ = 1), the reconstruction becomes:

    L_out ≈ [(1 - f₀)·DFG₁ + f₀·DFG₂] × LD(n, α)

where:
- `DFG₁` captures the Schlick Fresnel power `Fc = (1 - v·h)⁵` weighted contribution
- `DFG₂` captures the total (Fresnel-independent) contribution

## 2. Quasi-Random Sampling: Hammersley Sequence

The Hammersley point set generates well-distributed 2D samples on [0,1)²:

    u_i = (i/N, Φ₂(i))

where `Φ₂(i)` is the radical inverse function in base 2 (van der Corput sequence). To compute `Φ₂`, reverse the bits of the integer `i` (treating it as a 32-bit unsigned integer) and divide by 2³²:

    Φ₂(i) = reverse_bits_32(i) × 2.3283064365386963 × 10⁻¹⁰

The bit-reversal can be implemented efficiently via successive swaps:
- Swap 16-bit halves
- Swap adjacent pairs of bits
- Swap adjacent nibbles (groups of 2 bits → groups of 4)
- Swap adjacent bytes within 16-bit halves
- Swap adjacent bytes

## 3. GGX Normal Distribution Function (NDF)

The Trowbridge-Reitz / GGX distribution:

    D_GGX(n·h, α) = α² / (π · ((n·h)² · (α² - 1) + 1)²)

where `α` is the linear roughness (= perceptualRoughness²).

For numerical stability, the denominator can be rewritten using `(α²-1) = (α-1)(α+1)`:

    f = (α - 1) · ((α + 1) · (n·h)²) + 1
    D = α² / (π · f²)

## 4. Importance Sampling GGX

To importance-sample the GGX distribution, generate half-vectors `H` from 2D samples `(u₁, u₂)`:

    φ = 2π · u₁
    cos²θ = (1 - u₂) / (1 + (α + 1) · (α - 1) · u₂)
    cosθ = √(cos²θ)
    sinθ = √(1 - cos²θ)

    H = (sinθ·cos(φ), sinθ·sin(φ), cosθ)

All calculations are in tangent space where `n = (0, 0, 1)`.

The view vector `V` is constructed from `n·v`:

    V = (√(1 - (n·v)²), 0, n·v)

The light direction `L` is the reflection of `V` around `H`:

    L = 2·(V·H)·H - V

Then: `n·l = L.z`, `n·h = H.z`, `v·h = V·H` (all clamped to [0, 1]).

The PDF of this sampling scheme is: `pdf = D(h) · (n·h) / (4 · v·h)`

## 5. Smith-GGX Height-Correlated Visibility

The height-correlated Smith visibility function (already divided by `4·(n·v)·(n·l)` from the Cook-Torrance denominator):

    V(v, l, α) = 0.5 / (n·l · √((n·v)² · (1 - α²) + α²) + n·v · √((n·l)² · (1 - α²) + α²))

where `α` is the linear roughness. This is the *visibility* function, not the geometric shadowing function — the factor of `4·(n·v)·(n·l)` from the specular BRDF denominator is already incorporated.

## 6. DFG Integration (Multiscatter)

Assuming `f₉₀ = 1` and using the Schlick Fresnel approximation `F(v,h) = f₀(1-Fc) + Fc` where `Fc = (1 - v·h)⁵`:

For each `(n·v, α)` pair, compute over N importance samples:

    DFG₁(α, n·v) = (4/N) · Σᵢ Fc(v·hᵢ) · V(v, lᵢ, α) · (v·hᵢ / n·hᵢ) · n·lᵢ

    DFG₂(α, n·v) = (4/N) · Σᵢ          V(v, lᵢ, α) · (v·hᵢ / n·hᵢ) · n·lᵢ

Only accumulate samples where `n·l > 0`. Use N = 1024 samples.

The factor of 4 compensates for the Jacobian `|J(h)| = 1/(4·v·h)` that appears in the importance sampling PDF, which cancels with the BRDF's `D(h)·(n·h)` term but leaves the factor of 4 when combined with the `v·h/(n·h)` ratio.

## 7. Cloth Sheen Model

### Charlie Distribution (NDF)

The Estevez-Kulla "Production Friendly Microfacet Sheen BRDF" distribution:

    D_Charlie(n·h, α) = (2 + 1/α) · sin²θ^(1/(2α)) / (2π)

where `sin²θ = 1 - (n·h)²` and `α` is the linear roughness. Note: use `max(sin²θ, ε)` to avoid `0^x` issues.

### Ashikhmin Visibility

The Neubelt-Pettineo visibility for cloth:

    V_Ashikhmin(n·v, n·l) = 1 / (4 · (n·l + n·v - n·l · n·v))

### Cloth DFG Integration

Use **uniform hemisphere sampling** (not importance sampling):

    H = (sinθ·cos(φ), sinθ·sin(φ), cosθ)

where:
    φ = 2π · u₁
    cosθ = 1 - u₂
    sinθ = √(1 - cosθ²)

For each sample where `n·l > 0`:

    DFG_Charlie = (4 · 2π / N) · Σᵢ V_Ashikhmin(n·v, n·lᵢ) · D_Charlie(n·hᵢ, α) · n·lᵢ · v·hᵢ

The `v·h` factor comes from the Jacobian: the reflection formula introduces `|J(h)| = 1/(4·v·h)`, and the uniform hemisphere PDF is `1/(2π)`. The `4` and `2π` in the prefactor account for both.

Use N = 4096 samples.

## 8. Output Format

Write a binary file to `/app/output/dfg_lut.bin` with this layout:

| Offset | Size | Type | Description |
|--------|------|------|-------------|
| 0 | 4 | char[4] | Magic bytes: `DFGL` (ASCII) |
| 4 | 4 | uint32 LE | Width (128) |
| 8 | 4 | uint32 LE | Height (128) |
| 12 | 4 | uint32 LE | Channels (3) |
| 16 | W×H×C×4 | float32 LE | Pixel data, row-major |

Pixel data is stored row-major, with `y = 0` as the **top** row of the LUT (highest roughness). Each pixel has 3 float32 values: `(DFG₁, DFG₂, DFG_Charlie)`.

## 9. LUT Coordinate Mapping

For a LUT of size S×S (S = 128):

- **X axis** (horizontal, n·v):

      n·v = (x + 0.5) / S

  where `x ∈ [0, S-1]`. At x=0, n·v ≈ 0.004 (grazing). At x=S-1, n·v ≈ 0.996 (normal).

- **Y axis** (vertical, roughness):

      coord = (S - y + 0.5) / S

  where `y ∈ [0, S-1]`. At y=0 (top row), coord ≈ 1.0 (maximum roughness). At y=S-1 (bottom row), coord ≈ 0.012 (minimum roughness).

  The linear roughness is the **square** of the coordinate:

      linear_roughness = coord²

  This `coord = √(linear_roughness)` mapping ensures that lower mip levels (higher roughness) get more resolution in the LUT, matching the non-linear perceptual importance of roughness.
