# Filament PBR BRDF Specification


This document describes the physically based rendering (PBR) BRDF formulations
used by this library. All functions should produce numerically matching results
when implemented exactly as specified.

## Notation

| Symbol | Definition |
|--------|-----------|
| v | View unit vector |
| l | Incident light unit vector |
| n | Surface normal unit vector |
| h | Half unit vector between l and v: h = normalize(v + l) |
| f_d | Diffuse component of the BRDF |
| f_r | Specular component of the BRDF |
| alpha | Linear roughness = perceptualRoughness^2 |
| f0 | Reflectance at normal incidence |
| f90 | Reflectance at grazing angle (typically 1.0) |

Dot products are clamped to [0, 1] unless otherwise noted. In the BRDF
evaluation, NoV uses `abs(dot(n,v)) + 1e-5` (absolute value plus epsilon).

## 1. Standard Material Model

The BRDF is composed of a specular term f_r and a diffuse term f_d:

    f(v, l) = f_d(v, l) + f_r(v, l)

### 1.1 Roughness Remapping

The user-facing parameter `perceptualRoughness` is remapped to the linear
roughness used in BRDF equations:

    alpha = perceptualRoughness^2

### 1.2 Specular BRDF (Cook-Torrance)

    f_r(v, l) = D(h, alpha) * V(v, l, alpha) * F(v, h, f0)

where V is the **visibility function**, not the raw geometric term G.

#### 1.2.1 Normal Distribution Function (GGX / Trowbridge-Reitz)

    D_GGX(NoH, alpha) = alpha^2 / (pi * ((NoH)^2 * (alpha^2 - 1) + 1)^2)

Optimized implementation:

    float D_GGX(float NoH, float a) {
        float a2 = a * a;
        float f = (NoH * a2 - NoH) * NoH + 1.0;
        return a2 / (PI * f * f);
    }

#### 1.2.2 Geometric Visibility (Height-Correlated Smith GGX)

**Important**: The full geometric shadowing-masking function G_2 and the
visibility function V are related by:

    V(v, l, alpha) = G_2(v, l, alpha) / (4 * NoV * NoL)

This library provides and uses the **visibility form** V, which absorbs the
Cook-Torrance denominator 1/(4*NoV*NoL). Consequently, the specular BRDF is
simply:

    f_r = D * V * F

rather than the equivalent form `f_r = D * G * F / (4 * NoV * NoL)`. This
distinction is critical when deriving Monte Carlo estimators for BRDF
integration (see Section 3).

Implementation (height-correlated Smith form, optimized for numerical precision):

    float V_SmithGGXCorrelated(float NoV, float NoL, float a) {
        float a2 = a * a;
        float GGXL = NoV * sqrt((-NoL * a2 + NoL) * NoL + a2);
        float GGXV = NoL * sqrt((-NoV * a2 + NoV) * NoV + a2);
        return 0.5 / (GGXV + GGXL);
    }

#### 1.2.3 Fresnel (Schlick Approximation)

    F_Schlick(u, f0) = f0 + (1 - f0) * (1 - u)^5

where u is typically LoH (= VoH for the half vector). f0 is a per-channel RGB
value for metals, scalar for dielectrics.

### 1.3 Diffuse BRDF (Lambertian)

    f_d = diffuseColor / pi

    diffuseColor = baseColor * (1 - metallic)

### 1.4 Material Parameters

| Parameter | Type | Range | Description |
|-----------|------|-------|-------------|
| baseColor | float3 | [0,1] | Diffuse albedo (dielectrics) or specular color (metals) |
| metallic | float | [0,1] | 0 = dielectric, 1 = conductor |
| roughness | float | [0,1] | Perceptual roughness |
| reflectance | float | [0,1] | Controls dielectric f0 |

### 1.5 f0 Computation

f0 (specular reflectance at normal incidence) combines dielectric and metallic:

    f0 = 0.16 * reflectance^2 * (1 - metallic) + baseColor * metallic

For reflectance = 0.5, this gives f0 = 0.04 for dielectrics (4% reflectance,
corresponding to IOR 1.5).

### 1.6 Complete Standard BRDF Evaluation

Given spherical angles (theta_v, theta_l, phi_l) and a Material:

    // Convert spherical angles (degrees) to Cartesian directions
    V = (sin(theta_v), 0, cos(theta_v))
    L = (sin(theta_l)*cos(phi_l), sin(theta_l)*sin(phi_l), cos(theta_l))

    h = normalize(V + L)
    NoV = abs(V.z) + 1e-5
    NoL = clamp(L.z, 0, 1)
    NoH = clamp(h.z, 0, 1)
    LoH = clamp(dot(L, h), 0, 1)

    // Early exit if light below horizon
    if NoL <= 0: all outputs are zero

    roughness = perceptualRoughness^2
    f0 = 0.16 * reflectance^2 * (1 - metallic) + baseColor * metallic
    diffuseColor = baseColor * (1 - metallic)

    D = D_GGX(NoH, roughness)
    V = V_SmithGGXCorrelated(NoV, NoL, roughness)
    F = F_Schlick(LoH, f0)           // per-channel for RGB f0

    specular = D * V * F             // per-channel
    diffuse = diffuseColor / pi      // per-channel
    total = (specular + diffuse) * NoL

## 2. Clear Coat Model

Adds a second specular lobe representing a thin, transparent, dielectric layer
(e.g., car paint lacquer, polyurethane varnish). The clear coat has IOR 1.5
giving f0 = 0.04.

### 2.1 Clear Coat BRDF

Uses GGX NDF but with **Kelemen visibility** (simpler, cheaper):

    V_Kelemen(LoH) = 0.25 / (LoH^2)

Clear coat computation:

    ccRoughness = clearCoatPerceptualRoughness^2

    Dc = D_GGX(NoH, ccRoughness)
    Vc = V_Kelemen(LoH)
    Fc = F_Schlick(LoH, 0.04) * clearCoat   // clearCoat is the layer strength

    clearcoatBRDF = Dc * Vc * Fc

### 2.2 Energy Conservation with Clear Coat

The base layer (diffuse + specular) is attenuated by (1 - Fc) to account for
light absorbed/reflected by the clear coat:

    total = ((diffuse + specular * (1 - Fc)) * (1 - Fc) + clearcoatBRDF) * NoL

Note: the base specular and diffuse terms are computed identically to the
standard model (Section 1), using the same material parameters and dot products.
Only the final compositing differs.

### 2.3 Clear Coat Parameters

| Parameter | Type | Range | Description |
|-----------|------|-------|-------------|
| clearCoat | float | [0,1] | Clear coat layer strength |
| clearCoatRoughness | float | [0,1] | Perceptual roughness of clear coat |

## 3. DFG LUT / Split-Sum BRDF Integration

For image-based lighting (IBL), the BRDF integration is precomputed into a 2D
lookup table indexed by (NoV, perceptualRoughness). This is the "DFG" or "DFV"
table used in the split-sum approximation.

### 3.1 DFG Computation (Monte Carlo Integration)

For each (NoV, linearRoughness) pair, integrate the specular BRDF reflectance
over the hemisphere using importance sampling of the GGX distribution.

Setup in tangent space (N = [0, 0, 1]):

    V = (sqrt(1 - NoV^2), 0, NoV)

For each sample i in [0, numSamples):
    u = hammersley(i, 1/numSamples)
    H = importanceSampleGGX(u, linearRoughness)
    L = 2 * dot(V, H) * H - V     // reflect V around H

    VoH = saturate(dot(V, H))
    NoL = saturate(L.z)
    NoH = saturate(H.z)

    if NoL > 0:
        The Monte Carlo estimator approximates the hemispherical reflectance:

            E = integral over hemisphere of f_r(v, l) * cos(theta_l) * d_omega_l

        where f_r = D * V_vis * F uses the **visibility form** that already
        absorbs the 1/(4*NoV*NoL) denominator (see Section 1.2.2).

        The importance sampling PDF in half-vector space is:

            p(H) = D_GGX(NoH, alpha) * NoH

        Converting from H-space to L-space via the reflection Jacobian:

            |d_omega_H / d_omega_L| = 1 / (4 * VoH)

        Therefore the L-space PDF is:

            p(L) = D_GGX(NoH, alpha) * NoH / (4 * VoH)

        The per-sample Monte Carlo weight is the integrand (f_r * NoL) divided
        by the L-space PDF. Work through the cancellation: the D_GGX term in
        the integrand's f_r cancels with the D_GGX term in the PDF, and the
        remaining geometric factors yield the per-sample weight.

        After separating the Fresnel term:

            Fc = (1 - VoH)^5

        Accumulate:

            DFV.x += weight * (1 - Fc)    // f0 scale
            DFV.y += weight * Fc           // f90 scale

Apply the final normalization to DFV.x and DFV.y.

At runtime: Er = f0 * DFV.x + f90 * DFV.y

### 3.2 Hammersley Low-Discrepancy Sequence

    hammersley(i, invN) = (i * invN, radical_inverse_vdc(i))

    radical_inverse_vdc(bits):
        bits = (bits << 16) | (bits >> 16)           // all operations mod 2^32
        bits = ((bits & 0x55555555) << 1) | ((bits & 0xAAAAAAAA) >> 1)
        bits = ((bits & 0x33333333) << 2) | ((bits & 0xCCCCCCCC) >> 2)
        bits = ((bits & 0x0F0F0F0F) << 4) | ((bits & 0xF0F0F0F0) >> 4)
        bits = ((bits & 0x00FF00FF) << 8) | ((bits & 0xFF00FF00) >> 8)
        return float(bits) * 2.3283064365386963e-10   // = 1 / 0x100000000

### 3.3 GGX Importance Sampling

Given a 2D uniform sample u = (u1, u2), generate a half vector H from the GGX
distribution in tangent space (N = [0, 0, 1]):

    phi = 2 * pi * u1
    cosTheta^2 = (1 - u2) / (1 + (alpha + 1) * ((alpha - 1) * u2))
    // Note: (alpha+1)*(alpha-1) == alpha^2 - 1, factored for precision
    cosTheta = sqrt(cosTheta^2)
    sinTheta = sqrt(1 - cosTheta^2)

    H = (sinTheta * cos(phi), sinTheta * sin(phi), cosTheta)

The PDF of this distribution is: `pdf = D_GGX(NoH, alpha) * NoH / (4 * VoH)`
(after applying the reflection Jacobian to convert from H-space to L-space).

## 4. Multi-Scatter Energy Compensation

Single-scatter BRDFs lose energy at high roughness because they don't account
for light bouncing between microfacets. An energy compensation term recovers
this lost energy.

### 4.1 Directional Albedo

The directional albedo E is the total reflected energy for a white furnace
(f0 = f90 = 1):

    E(NoV, roughness) = DFV.x + DFV.y

### 4.2 Energy Compensation Factor

The specular BRDF is scaled by an energy compensation factor:

    energyCompensation = 1 + f0 * (1/E - 1)

When E = 1 (no energy loss), compensation = 1. When E < 1, the factor adds
back lost energy proportionally to f0 (metals lose more visible energy because
their specular is colored).

## 5. Input/Output Format

### Input: /app/config.json

Contains four evaluation sections:
- `dfg_evaluations`: Compute DFV.x (dfg1) and DFV.y (dfg2) for given (NoV, perceptual_roughness, num_samples)
- `brdf_evaluations`: Evaluate standard BRDF for given directions and material
- `clear_coat_evaluations`: Evaluate clear coat BRDF
- `energy_compensation`: Compute energy compensation factors

Directions are specified as spherical angles in degrees:
- theta_v: polar angle of view direction from normal (0 = looking straight at surface)
- theta_l: polar angle of light direction from normal
- phi_l: azimuthal angle of light direction (phi_v = 0 always)

### Output: /app/output.json

JSON object keyed by evaluation ID. Each entry contains the computed values:
- DFG: `{"dfg1": float, "dfg2": float}`
- BRDF: `{"specular": [r,g,b], "diffuse": [r,g,b], "total": [r,g,b]}`
  where total = (specular + diffuse) * NoL
- Clear coat: `{"specular": [r,g,b], "diffuse": [r,g,b], "clearcoat_specular": float, "total": [r,g,b]}`
- Energy compensation: `{"E": float, "compensation": [r,g,b]}`

## 6. C Struct Layout

The Material struct in the C library uses this field order:

    typedef struct {
        float baseColor[3];
        float roughness;
        float metallic;
        float reflectance;
        float clearCoat;
        float clearCoatRoughness;
    } Material;

The Python ctypes definition must exactly match this layout for correct
foreign function interface (FFI) data passing.
