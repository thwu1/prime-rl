# Fire Behavior Equations Reference

## Surface Fire Spread Rate

The no-wind no-slope rate of spread is:

    R₀ = (I_R · ξ) / (ρ_b · ε̄ · Q̄_ig)

With wind and slope, the heading (maximum) spread rate is:

    R_max = R₀ · (1 + φ_eff)

where φ_eff is the combined wind-slope factor magnitude.

## Fuel Component Classification and Weighting

Fuels are separated into **dead** and **live** categories.

Dead components: 1-hour, 10-hour, 100-hour, and (for dynamic models) transferred herbaceous.
Live components: herbaceous and woody.

Surface area of component i:

    A_i = σ_i · w₀_i / ρ_p

Component fraction within a category:

    f_i = A_i / ΣA_category

Category fraction:

    f_cat = ΣA_category / ΣA_total

Characteristic SAV:

    σ = Σ(f_cat · Σ(f_i · σ_i))

Standard SAV values: 10-hour = 109 1/ft, 100-hour = 30 1/ft.

## Size Class Grouping

Components are grouped by SAV into size classes with boundaries at 1200, 192, 96, 48, 16 (1/ft). Net fuel loading for each category sums the net loads w₀·(1 − S_T) within each size class, weighted by the sum of component fractions in that class.

## Bulk Density and Packing

    ρ_b = Σw₀ / δ          (total load / fuel bed depth)
    β = ρ_b / ρ_p           (packing ratio)
    β_op = 3.348 · σ^(−0.8189)  (optimum packing ratio)

## Reaction Velocity

    A = 133 · σ^(−0.7913)
    Γ_max = σ^1.5 / (495 + 0.0594 · σ^1.5)
    Γ = Γ_max · (β/β_op)^A · exp(A · (1 − β/β_op))

## Moisture Damping

Per-category weighted fuel moisture:

    M_f = Σ(f_i · M_i)

Moisture damping coefficient:

    η_M = 1 − 2.59·r + 5.11·r² − 3.52·r³     where r = min(M_f / M_x, 1)

## Mineral Damping

    η_s = min(0.174 · S_e^(−0.19), 1)

## Live Fuel Moisture of Extinction

Fine dead weighting:  w_d,i = load_i · exp(−138/σ_i)
Fine live weighting:  w_l,i = load_i · exp(−500/σ_i)
Weight ratio:  W = Σw_d / Σw_l
Fine dead moisture (weighted):  M_fd = Σ(M_i · w_d,i) / Σw_d,i

    M_x,live = max(2.9 · W · (1 − M_fd / M_x,dead) − 0.226, M_x,dead)

## Reaction Intensity

    I_R = Γ · Σ_cat(w_n,cat · h_cat · η_M,cat · η_s)

where h = heat content (8000 Btu/lb for all standard models).

## Propagating Flux Ratio

    ξ = exp((0.792 + 0.681·√σ) · (β + 0.1)) / (192 + 0.2595·σ)

## Effective Heating and Heat of Preignition

    ε_i = exp(−138/σ_i)
    Q_ig,i = 250 + 1116·M_i

Heat sink (denominator of the ROS equation):

    ρ_b · Σ_cat(f_cat · Σ(f_i · ε_i · Q_ig,i))

## Wind Factor

    φ_w = C · U^B · (β/β_op)^(−E)

where:

    C = 7.47 · exp(−0.133 · σ^0.55)
    B = 0.02526 · σ^0.54
    E = 0.715 · exp(−3.59×10⁻⁴ · σ)
    U = midflame wind speed in ft/min (1 mph = 88 ft/min)

## Slope Factor

    φ_s = 5.275 · β^(−0.3) · tan²(slope)

where slope is in degrees.

## Wind-Slope Vector Combination

Wind and slope factors are combined as vectors in the horizontal plane:

- Wind vector: magnitude φ_w in the direction wind blows toward (180° from "direction_from")
- Slope vector: magnitude φ_s in the upslope direction (180° from aspect)
- Combined vector: V = V_wind + V_slope
- φ_eff = |V|
- Heading direction = azimuth of V (degrees CW from north)

Effective wind speed (for ellipse shape) is found by inverting the wind factor:

    U_eff = ((φ_eff · (β/β_op)^E) / C)^(1/B)

## Fire Ellipse Shape

Length-to-breadth ratio:

    LB = 0.936·exp(0.2566·U_mph) + 0.461·exp(−0.1548·U_mph) − 0.397

where U_mph = effective wind speed in mph. LB ≥ 1, capped at 8.

Eccentricity:

    e = √(1 − 1/LB²)     if LB > 1, else 0

Directional spread rate at angle θ from heading:

    R(θ) = R_max · (1 − e) / (1 − e·cos(θ))

## Fireline Intensity and Flame Length

    τ = 384/σ                    (residence time, minutes)
    H_A = I_R · τ               (heat per unit area, Btu/ft²)
    I_B = H_A · R / 60          (fireline intensity, Btu/ft/s)
    L_f = 0.45 · I_B^0.46       (flame length, ft)

## Dynamic Fuel Model Curing

For models flagged as dynamic, herbaceous load transfers from live to dead:

    cured_fraction = (1.20 − M_live_herb) / (1.20 − 0.30), clamped to [0, 1]

Dead herbaceous load = herb_load · cured_fraction (uses dead component moisture m_1h)
Live herbaceous load = herb_load · (1 − cured_fraction)

## Non-burnable Fuel Models

Models 91–93, 98, 99 are non-burnable: zero spread, block fire propagation.

## Constants

| Quantity | Value |
|----------|-------|
| Particle density (ρ_p) | 32 lb/ft³ |
| Total mineral content (S_T) | 0.0555 |
| Effective mineral content (S_e) | 0.010 |
| Heat content (h) | 8000 Btu/lb |
| 10h SAV | 109 1/ft |
| 100h SAV | 30 1/ft |

## Unit Conversions

- 1 ton/acre = 2000/43560 lb/ft²
- 1 mph = 88 ft/min
