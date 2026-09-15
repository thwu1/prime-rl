# Kudryavtsev Permafrost Model — Equation Specification

This document defines the complete equation chain for computing the temperature
at the top of permafrost (TTOP, denoted Tps) and active layer thickness (ALT,
denoted Zal) from climate, snow, soil, and vegetation parameters.

## Input Parameters

| Symbol | CSV Column | Description | Unit |
|--------|-----------|-------------|------|
| Ta | Ta | Mean annual air temperature | degC |
| Aa | Aa | Amplitude of annual air temperature | degC |
| Hsn | Hsn | Mean winter snow depth | m |
| rho_sn | rho_sn | Snow density | kg/m^3 |
| theta | vwc | Volumetric water content | m^3/m^3 |
| — | p_clay | Clay fraction of soil | dimensionless |
| — | p_sand | Sand fraction of soil | dimensionless |
| — | p_silt | Silt fraction of soil | dimensionless |
| — | p_peat | Peat fraction of soil | dimensionless |
| Hvgf | Hvgf | Vegetation height, frozen period | m |
| Hvgt | Hvgt | Vegetation height, thawed period | m |
| Dvf | Dvf | Vegetation thermal diffusivity, frozen | m^2/s |
| Dvt | Dvt | Vegetation thermal diffusivity, thawed | m^2/s |

Soil fractions must sum to 1.0.

## Step 1: Snow Thermal Properties

Snow thermal conductivity (Sturm et al. 1997, eq. 4):

    Ksn = (rho_sn / 1000)^2 * 3.233 - 1.01 * (rho_sn / 1000) + 0.138

Unit: W/(m*degC)

Snow heat capacity (constant):

    Csn = 2090

Unit: J/(kg*degC)

## Step 2: Soil Thermal Properties

The file `thermal_params.csv` provides per-texture values with columns:
Texture, Bulk_Density (BD) [kg/m^3], Heat_Capacity (HC) [J/(kg*degC)],
Thermal_Conductivity_Thawed (TCT) [W/(m*degC)], Thermal_Conductivity_Frozen (TCF) [W/(m*degC)].

Rows are ordered: Silt, Sand, Clay, Peat.

Bulk density (linear mixture):

    rho_b = BD_Silt * p_silt + BD_Sand * p_sand + BD_Clay * p_clay + BD_Peat * p_peat

Specific heat capacity (linear mixture):

    Cp = HC_Silt * p_silt + HC_Sand * p_sand + HC_Clay * p_clay + HC_Peat * p_peat

Volumetric heat capacity of soil:

    Ct = Cp * rho_b + 4190 * theta       (thawed)  [J/(m^3*degC)]
    Cf = Cp * rho_b + 2025 * theta       (frozen)  [J/(m^3*degC)]

Soil mineral thermal conductivity (geometric weighted mean):

    Kt_soil = TCT_Silt^p_silt * TCT_Sand^p_sand * TCT_Clay^p_clay * TCT_Peat^p_peat
    Kf_soil = TCF_Silt^p_silt * TCF_Sand^p_sand * TCF_Clay^p_clay * TCF_Peat^p_peat

Effective soil thermal conductivity (including water/ice content):

    Kt = Kt_soil^(1 - theta) * 0.54^theta       (thawed)  [W/(m*degC)]
    Kf = Kf_soil^(1 - theta) * 2.35^theta       (frozen)  [W/(m*degC)]

## Step 3: Season Lengths

    tau = 365 * 24 * 3600       (seconds in one year)

    tau1 = tau * (0.5 - arcsin(Ta / Aa) / pi)       (cold season length, seconds)
    tau2 = tau - tau1                                 (warm season length, seconds)

Requires |Ta| < Aa.

## Step 4: Volumetric Latent Heat

    L = 3.34e8 * theta       [J/m^3]

## Step 5: Snow Effect on Ground Temperature

Snow thermal diffusivity:

    alpha_sn = Ksn / (rho_sn * Csn)       [m^2/s]

Temperature shift due to snow insulation:

    delta_Tsn = Aa * (1 - exp(-Hsn * sqrt(pi / (tau * alpha_sn))))

Amplitude reduction due to snow:

    delta_Asn = (2 / pi) * delta_Tsn

Temperature and amplitude at the base of snow (top of vegetation):

    Tvg = Ta + delta_Tsn
    Avg = Aa - delta_Asn

## Step 6: Vegetation Effect on Ground Surface Temperature

Winter (frozen) amplitude reduction:

    delta_A1 = (Avg - Tvg) * (1 - exp(-Hvgf * sqrt(pi / (Dvf * 2 * tau1))))

Summer (thawed) amplitude reduction:

    delta_A2 = (Avg + Tvg) * (1 - exp(-Hvgt * sqrt(pi / (Dvt * 2 * tau2))))

If Hvgf = 0, set delta_A1 = 0. If Hvgt = 0, set delta_A2 = 0.

Combined vegetation effect on amplitude:

    delta_Av = (delta_A1 * tau1 + delta_A2 * tau2) / tau

Combined vegetation effect on mean temperature:

    delta_Tv = (delta_A1 * tau1 - delta_A2 * tau2) / tau * (2 / pi)

Ground surface temperature and amplitude:

    Tgs = Tvg + delta_Tv
    Ags = Avg - delta_Av

## Step 7: Temperature at Top of Permafrost (TTOP)

Define the ratio:

    r = Tgs / Ags

TTOP numerator:

    N = 0.5 * Tgs * (Kf + Kt) + Ags * (Kt - Kf) / pi * (r * arcsin(r) + sqrt(1 - r^2))

Regime classification:

    If N <= 0: permafrost regime, K_star = Kf
    If N > 0:  seasonal frost regime, K_star = Kt

Temperature at top of permafrost:

    Tps = N / K_star

## Step 8: Active Layer Thickness (permafrost regime only)

Applicable only when N <= 0 (permafrost). For seasonal frost (N > 0), ALT is undefined.

Use frozen-state properties: C = Cf, K = Kf.

Intermediate amplitude at permafrost table:

    Aps = (Ags - |Tps|) / ln((Ags + L/(2*C)) / (|Tps| + L/(2*C))) - L/(2*C)

First-order depth estimate:

    Zc = 2 * (Ags - |Tps|) * sqrt(K * tau * C / pi) / (2 * Aps * C + L)

Active layer thickness (refined estimate):

    Let S1 = sqrt(K * tau * C / pi)
    Let S2 = sqrt(K * tau / (pi * C))
    Let D  = 2 * Aps * C + L

    Zal = [2*(Ags - |Tps|)*S1 + ((2*Aps*C*Zc + L*Zc) * L * S2) / (2*Ags*C*Zc + L*Zc + D*S2)] / D

This yields the active layer thickness Zal in meters.

## Appendix: Numerical Differentiation Convention

When computing numerical derivatives of model outputs (TTOP, ALT) with
respect to input parameters, use centered finite differences:

    df/dp = (f(p + h) - f(p - h)) / (2h)

Step size:

    h = max(|p| * 1e-4, 1e-6)

When a perturbation causes a regime transition (e.g., ALT becomes undefined
because the perturbed state is seasonal frost), fall back to one-sided
differences from the base case. If both perturbation directions yield
undefined ALT, set the ALT derivative to zero for that parameter.
