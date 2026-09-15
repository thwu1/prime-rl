# WEPP Single-OFE Surface Hydrology: Equation Reference

This document describes the equations for the WEPP (Water Erosion Prediction
Project) surface hydrology model for a single overland flow element (OFE).

## 1. Green-Ampt Mein-Larson (GAML) Infiltration

### 1.1 Infiltration Capacity

When the soil surface is ponded, the infiltration rate is:

    f = Ke * (1 + N_s * theta_d / F)

where:
- f = infiltration rate (mm/hr)
- Ke = effective saturated hydraulic conductivity (mm/hr)
- N_s = effective matric potential at the wetting front (mm, positive)
- theta_d = soil moisture deficit = effective porosity - initial volumetric
  water content (dimensionless)
- F = cumulative infiltration depth (mm)

### 1.2 Cumulative Infiltration (Implicit Equation)

Cumulative infiltration under ponded conditions satisfies:

    F - N_s * theta_d * ln(1 + F / (N_s * theta_d)) = Ke * t_s

where t_s is the elapsed time (hours) since the start of ponded conditions
(adjusted for virtual time shift).

Define the auxiliary function:

    G(F) = F - N_s * theta_d * ln(1 + F / (N_s * theta_d))

Then at any ponded time t after ponding onset:

    G(F(t)) = G(F_p) + Ke * (t - t_p)

where F_p is cumulative infiltration at the moment of ponding and t_p is
the ponding time. Solve iteratively (e.g., Newton-Raphson) for F(t).

### 1.3 Unsteady Rainfall (Chu 1978 Method)

Process the rainfall hyetograph interval by interval (each interval has
constant intensity r_i):

**Pre-ponding phase** (while no surface ponding):
- All rainfall infiltrates: F increases at rate r_i
- Check for ponding onset: ponding occurs in interval i when both:
  (a) r_i > Ke, AND
  (b) cumulative rainfall R(t) reaches F_p = Ke * N_s * theta_d / (r_i - Ke)

**Ponding onset** (within interval):
- Compute the sub-interval time to reach F_p
- At the ponding moment: F = F_p, record ponding time t_p
- For the remainder of the interval, switch to ponded-phase computation

**Ponded phase**:
- Advance GAML: solve G(F_new) = G(F_old) + Ke * dt for each sub-interval
- Rainfall excess rate: v_i = r_i - f_i (where f_i is the GAML infiltration
  rate at current F)
- If rainfall intensity drops below infiltration capacity (r_i < f_i), then
  ponding ceases: revert to pre-ponding tracking. Set F = cumulative rain.
  The next ponding event uses a new F_p calculation.

**Ponding cessation and re-ponding**:
- When rainfall rate drops below infiltration capacity, ponding ceases.
- During non-ponded intervals, all rain infiltrates.
- When a subsequent interval has r_i > Ke, compute a new F_p for that rate:
  F_p_new = Ke * N_s * theta_d / (r_i - Ke)
- If cumulative infiltration already exceeds F_p_new, ponding is immediate.
- Otherwise, ponding occurs when cumulative rainfall reaches F_p_new.
- At re-ponding, compute a new virtual time offset:
  t_shift such that G(F_current) = Ke * t_shift
  Then subsequent ponded computation continues from this offset.

### 1.4 Newton-Raphson for GAML

To solve G(F) = target for F:

    g(F) = G(F) - target = F - N_s * theta_d * ln(1 + F/(N_s*theta_d)) - target
    g'(F) = 1 - N_s * theta_d / (F + N_s * theta_d) = F / (F + N_s * theta_d)

    F_{n+1} = F_n - g(F_n) / g'(F_n)

Initial guess: F_0 = F_old + Ke * dt. Iterate until |F_{n+1} - F_n| < 1e-8.

## 2. Depression Storage (Onstad 1984)

Maximum depression storage capacity:

    S_d = 0.112 * RR + 0.031 * RR^2 - 0.012 * RR * S_pct

where:
- S_d = maximum depression storage (mm), clamp to >= 0
- RR = random roughness of the soil surface (mm)
- S_pct = slope of the flow surface (percent, e.g., 5% slope -> S_pct = 5)

Depression storage is assumed to be filled before runoff begins. The net
rainfall excess available for runoff is:

    V_net = max(0, V_gross - S_d)

where V_gross is total rainfall excess depth (mm).

## 3. Peak Discharge (Approximate Method)

### 3.1 Chezy Depth-Discharge

The kinematic wave depth-discharge relationship using the Chezy equation:

    q = alpha * h^m

where:
- q = discharge per unit width (m^2/s)
- h = flow depth (m)
- alpha = C * sqrt(S_0) (depth-discharge coefficient, m^{0.5}/s)
- C = Chezy roughness coefficient (m^{0.5}/s, user input)
- S_0 = slope (dimensionless fraction, e.g., 0.05)
- m = 3/2 (Chezy exponent)

### 3.2 Time to Kinematic Equilibrium

    t_e = [ L / (alpha * v_bar_si^{m-1}) ]^{1/m}

where:
- t_e = time to equilibrium (seconds)
- L = OFE length (m)
- v_bar_si = average rainfall excess rate in SI units (m/s)
  = v_bar_mm_hr / 3.6e6
- v_bar_mm_hr = V_gross / D_r (average rainfall excess rate, mm/hr)
- D_r = duration of rainfall excess (hours) = time from first excess to
  last excess
- m = 3/2

For Chezy (m = 3/2):

    t_e = [ L / (alpha * sqrt(v_bar_si)) ]^{2/3}

### 3.3 Dimensionless Variables

    t_star = D_r_sec / t_e       (D_r in seconds)
    v_star = v_peak / v_bar       (peak-to-average excess rate ratio)

where v_peak = maximum instantaneous rainfall excess rate (mm/hr).

### 3.4 Dimensionless Peak Discharge

    q_star = q_peak / (v_bar * L)

For variable rainfall excess, the approximate equations are:

    q_star = t_star                 for t_star <= 1     [partial equilibrium]

    q_star = 1 + (v_star - 1) * (1 - 1/t_star^2)
                                    for t_star > 1      [near/full equilibrium]

    q_star = min(q_star, v_star)    (cap at v_star)

The dimensional peak discharge rate (as a depth rate over the OFE):

    q_peak = q_star * v_bar_mm_hr   (mm/hr)

### 3.5 Effective Runoff Duration

To maintain volume continuity between peak rate and total runoff volume:

    D_e = V_net / q_peak

where:
- D_e = effective runoff duration (hours)
- V_net = net runoff depth after depression storage adjustment (mm)
- q_peak = peak discharge rate (mm/hr)

## 4. Recession Infiltration (Simplified)

For partial equilibrium conditions (t_star < 1), some rainfall excess
re-infiltrates during the recession phase. The adjusted net runoff is:

    f_star = f_end / v_bar_mm_hr

where f_end is the infiltration rate (mm/hr) at the last moment of
non-zero rainfall excess.

    If f_star < 1 and t_star < 1:
        Q_star = 1 - (3/5) * f_star * t_star^(3/5)
        V_adjusted = V_net * max(0, Q_star)
    Else:
        V_adjusted = V_net

Replace V_net with V_adjusted in subsequent calculations.

## 5. Units Summary

| Quantity         | Symbol    | Units          |
|------------------|-----------|----------------|
| Hydraulic cond.  | Ke        | mm/hr          |
| Matric potential | N_s       | mm             |
| Moisture deficit | theta_d   | dimensionless  |
| Slope            | S_0       | fraction (e.g. 0.05) |
| Slope (for Sd)   | S_pct     | percent (e.g. 5)     |
| Random roughness | RR        | mm             |
| Chezy coeff.     | C         | m^{0.5}/s      |
| OFE length       | L         | m              |
| Rainfall rate    | r         | mm/hr          |
| Time             | t         | minutes (input), hours/seconds (internal) |
