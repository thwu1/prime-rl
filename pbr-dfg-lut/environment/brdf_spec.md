# PBR DFG Pre-Integration LUT — Mathematical Specification


## 1. Overview

In the split-sum approximation for image-based lighting (IBL), specular reflections are decomposed as:

    L_out ≈ [(1 - f₀)·DFG₁ + f₀·DFG₂] × LD(n, α)

where:
- `f₀` = base reflectance at normal incidence
- `LD` = pre-filtered environment radiance
- `DFG₁` = Fc-weighted visibility integral (see Section 6)
- `DFG₂` = total visibility integral (see Section 6)
- `α` = linear roughness

The DFG terms depend only on the view angle `cos(θ) = n·v` and roughness `α`, making them suitable for pre-computation into a 2D lookup table.

The LUT stores three channels per pixel:
- **Red (DFG₁)**: Schlick Fresnel Fc-weighted visibility
- **Green (DFG₂)**: Total (unweighted) visibility
- **Blue (DFG_Charlie)**: Cloth sheen DFG value

## 2. Quasi-Random Sampling: Hammersley Sequence

The Hammersley point set generates well-distributed 2D samples on [0,1)²:

    uᵢ = (i/N, Φ₂(i))

where `Φ₂(i)` is the radical inverse function in base 2 (van der Corput sequence). To compute `Φ₂`, reverse the bits of the integer `i` (treating it as a 32-bit unsigned integer) and divide by 2³²:

    Φ₂(i) = reverse_bits_32(i) × 2.3283064365386963 × 10⁻¹⁰

The bit-reversal can be implemented efficiently via successive swaps:
1. Swap the upper and lower 16-bit halves of the word
2. Within each half, swap adjacent single bits (mask: 0x55555555 / 0xAAAAAAAA)
3. Swap adjacent pairs of bits (mask: 0x33333333 / 0xCCCCCCCC)
4. Swap adjacent nibbles (mask: 0x0F0F0F0F / 0xF0F0F0F0)
5. Swap adjacent bytes (mask: 0x00FF00FF / 0xFF00FF00)

All intermediate results must be masked to 32 bits.

## 3. GGX Normal Distribution Function (NDF)

The Trowbridge-Reitz / GGX distribution:

    D_GGX(n·h, α) = α² / (π · ((n·h)² · (α² - 1) + 1)²)

where `α` is the linear roughness (not perceptual roughness).

For numerical stability near `α ≈ 0`, factor the denominator using `(α²-1) = (α-1)(α+1)`:

    f = (α - 1) · ((α + 1) · (n·h)²) + 1
    D = α² / (π · f²)

## 4. Importance Sampling GGX

To importance-sample the GGX distribution, generate half-vectors `H` in tangent space where `n = (0, 0, 1)`. From 2D samples `(u₁, u₂)`:

    φ = 2π · u₁
    cos²θ = (1 - u₂) / (1 + (α + 1) · (α - 1) · u₂)
    cosθ = √(cos²θ)
    sinθ = √(1 - cos²θ)

    H = (sinθ·cos(φ), sinθ·sin(φ), cosθ)

Clamp `cos²θ` to [0, 1] to avoid numerical issues.

The view vector `V` is constructed from `n·v`:

    V = (√(1 - (n·v)²), 0, n·v)

The light direction `L` is the reflection of `V` around `H`:

    L = 2·(V·H)·H - V

Then compute the following dot products, each saturated (clamped) to [0, 1]:
- `n·l = L.z`
- `n·h = H.z`
- `v·h = V·H`

## 5. Smith-GGX Visibility Functions

Two forms of the Smith visibility function appear in production PBR renderers. Both incorporate the Cook-Torrance `1/(4·n·v·n·l)` denominator directly, yielding a "visibility" function rather than a raw geometry/masking function.

### Option A: Height-Correlated (Heitz 2014)

Accounts for the correlation between masking and shadowing heights in the microsurface model:

    GGXV = n·l · √( (n·v - n·v · α²) · n·v + α² )
    GGXL = n·v · √( (n·l - n·l · α²) · n·l + α² )
    V = 0.5 / (GGXV + GGXL)

where `α` is the linear roughness. Use `max(0, ...)` inside the square roots to prevent negative arguments.

Reference: Heitz, "Understanding the Masking-Shadowing Function in Microfacet-Based BRDFs" (2014).

### Option B: Separable Approximation (Schlick-GGX)

Decomposes the joint visibility into independent masking and shadowing terms:

    k = α / 2
    V = 1 / (4 · ((n·v)·(1-k) + k) · ((n·l)·(1-k) + k))

Reference: Schlick approximation of Smith's masking-shadowing function.

### Choosing Between Options

Both are physically motivated approximations. Your implementation must evaluate **both** options numerically at the diagnostic coordinates specified in Section 10. Compare the DFG values produced by each to determine which maintains correct energy-conservation properties and produces physically plausible results across the full range of view angles and roughness values.

## 6. DFG Multiscatter Integration

For the multiscatter formulation (f₉₀ = 1), the Schlick Fresnel approximation gives:

    F(v,h) = f₀·(1 - Fc) + Fc

where `Fc = (1 - v·h)⁵`. Factoring out `f₀` allows storing two terms separately:

    Er() = (1 - f₀)·DFG₁ + f₀·DFG₂

For each `(n·v, α)` pair, iterate over `N` importance samples of the GGX distribution. For each sample `i` where `n·l > 0`:

    v_term_i = V(n·v, n·l, α) · n·l · (v·h / n·h)

Accumulate:

    DFG₁ = (4/N) · Σᵢ  Fc_i · v_term_i

    DFG₂ = (4/N) · Σᵢ  v_term_i

The factor of 4 compensates for the Jacobian `|J(h)| = 1/(4·v·h)` in the importance sampling PDF. When the GGX distribution `D(h)·(n·h)` cancels between the BRDF numerator and the PDF denominator, the remaining integrand is `V(v,l) · (v·h / n·h) · n·l`, scaled by 4.

Use **N = 1024** samples for the GGX integration.

## 7. Cloth Sheen Model

### 7.1 Charlie Distribution (NDF)

The Estevez-Kulla "Production Friendly Microfacet Sheen BRDF" distribution:

    D_Charlie(n·h, α) = (2 + 1/α) · sin²θ ^ (1/(2α)) / (2π)

where `sin²θ = 1 - (n·h)²` and `α` is the linear roughness. Use `max(sin²θ, 10⁻¹²)` to avoid `0^x` numerical issues. Return 0 when `α` is negligibly small (< 10⁻⁷).

### 7.2 Ashikhmin Visibility

The Neubelt-Pettineo visibility function for cloth materials:

    V_Ashikhmin(n·v, n·l) = 1 / (4 · (n·l + n·v - n·l · n·v))

### 7.3 Cloth DFG Integration

Use **uniform hemisphere sampling** for cloth (not GGX importance sampling):

    φ = 2π · u₁
    cosθ = 1 - u₂
    sinθ = √(1 - cosθ²)
    H = (sinθ·cos(φ), sinθ·sin(φ), cosθ)

The uniform hemisphere PDF is `1/(2π)`. Compute V and H as in Section 4 to obtain L, n·l, n·h, v·h. For each sample where `n·l > 0`, accumulate:

    DFG_Charlie = (4 · 2π / N) · Σᵢ V_Ashikhmin(n·v, n·lᵢ) · D_Charlie(n·hᵢ, α) · n·lᵢ · v·hᵢ

The `v·h` factor comes from the reflection Jacobian `|J(h)| = 1/(4·v·h)`. The `4` and `2π` in the prefactor compensate for the uniform sampling PDF and the Jacobian cancellation.

Use **N = 4096** samples for the cloth integration.

## 8. Output Format

Write the LUT binary file to `/app/output/dfg_lut.bin` with this layout:

| Offset | Size | Type | Description |
|--------|------|------|-------------|
| 0 | 4 | char[4] | Magic bytes: `DFGL` (ASCII) |
| 4 | 4 | uint32 LE | Width (128) |
| 8 | 4 | uint32 LE | Height (128) |
| 12 | 4 | uint32 LE | Channels (3) |
| 16 | W×H×C×4 | float32 LE | Pixel data, row-major |

Pixel data is stored row-major with `y = 0` as the **top** row of the LUT (highest roughness). Each pixel contains 3 float32 values in channel order: `(DFG₁, DFG₂, DFG_Charlie)`.

## 9. LUT Coordinate Mapping

For a LUT of size S×S (S = 128):

**X axis** (horizontal, n·v):

    n·v = saturate((x + 0.5) / S)

where `x ∈ [0, S-1]`. At `x = 0`: `n·v ≈ 0.004` (grazing angle). At `x = S-1`: `n·v ≈ 0.996` (normal incidence).

**Y axis** (vertical, roughness):

    coord = saturate((S - y + 0.5) / S)

where `y ∈ [0, S-1]`. At `y = 0` (top row): `coord ≈ 1.004` → saturated to 1.0 (maximum roughness). At `y = S-1` (bottom row): `coord ≈ 0.012` (minimum roughness).

The linear roughness is the **square** of the coordinate:

    linear_roughness = coord²

This perceptual mapping (`coord = √linear_roughness`) allocates more LUT resolution to lower roughness values where visual changes are more perceptible.

## 10. Evaluation Requirements

You must implement **both** visibility functions from Section 5 and evaluate them numerically.

For each of the following diagnostic coordinates, compute DFG₁ and DFG₂ using both visibility function options:

    Diagnostic coordinates: (64, 64), (0, 0), (127, 127), (32, 96), (96, 32)

Write your evaluation to `/app/output/analysis.json` with this structure:

```json
{
    "chosen_visibility": "height_correlated" or "separable",
    "justification": "<brief explanation of your choice>",
    "comparison_data": [
        {
            "x": 64, "y": 64,
            "height_correlated": {"dfg1": <float>, "dfg2": <float>},
            "separable": {"dfg1": <float>, "dfg2": <float>}
        }
    ]
}
```

After selecting the correct visibility function based on your evaluation, use it to generate the final LUT.
