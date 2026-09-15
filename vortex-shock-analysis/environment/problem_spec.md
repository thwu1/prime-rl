# HiOCFD5 CI2: Strong Vortex-Shock Wave Interaction — Initial Condition Analysis

## Physical Setup

This benchmark problem defines the initial condition for a 2D inviscid compressible flow
simulation of a strong vortex interacting with a stationary normal shock wave, based on the
CI2 test case from the 5th International Workshop on High-Order CFD Methods (HiOCFD5).

- **Governing equations**: 2D Euler equations for an ideal gas
- **Specific heat ratio**: gamma = 1.4
- **Specific gas constant**: R = 1.0
- **Domain**: [0, 1] x [0, 1]
- **Shock location**: x = 0.5 (stationary normal shock)

## Upstream Conditions (x <= 0.5)

The far-field upstream state (away from the vortex) is:
- Density: rho_u = 1.0
- x-velocity: u_u = 1.5 * sqrt(gamma)
- y-velocity: v_u ~ 0 (use 1e-20 for numerical stability)
- Pressure: p_u = 1.0
- Temperature: T_u = p_u / (rho_u * R) = 1.0

## Downstream Conditions (x > 0.5)

Apply the Rankine-Hugoniot normal shock relations with shock Mach number Ms = 1.5:

    rho_d = rho_u * (gamma+1)*Ms^2 / (2 + (gamma-1)*Ms^2)
    u_d   = u_u * (2 + (gamma-1)*Ms^2) / ((gamma+1)*Ms^2)
    v_d   = v_u
    p_d   = p_u * (1 + 2*gamma/(gamma+1) * (Ms^2 - 1))
    T_d   = p_d / (rho_d * R)

## Vortex Superposition

A compound vortex is superimposed on the upstream flow, centered at (x_c, y_c) = (0.25, 0.5):

- Inner core radius: a = 0.075
- Outer cutoff radius: b = 0.175
- Vortex Mach number: M_v = 0.9
- Maximum tangential velocity: v_m = M_v * sqrt(gamma)

Define: r = distance from (x_c, y_c), theta = angle from center
        cos(theta) = (x - x_c)/r, sin(theta) = (y - y_c)/r

### For r <= b (within vortex influence):

**Inner core (r <= a, r > 0):**

Tangential velocity magnitude: v_theta = v_m * r / a

Velocity modification:
    u = u_u - v_theta * sin(theta)
    v = v_u + v_theta * cos(theta)

Temperature at r = a (boundary value, computed from outer formula):
    R_a = -2*b^2*ln(b) - a^2/2 + 2*b^2*ln(a) + b^4/(2*a^2)
    T_a = T_u - (gamma-1) * [v_m * a / (a^2 - b^2)]^2 * R_a / (R*gamma)

Inner core temperature (r <= a):
    R_inner = (1 - r^2/a^2) / 2
    T = T_a - (gamma-1) * v_m^2 * R_inner / (R*gamma)

**Outer annular region (a < r <= b):**

Tangential velocity magnitude: v_theta = v_m * a * (r - b^2/r) / (a^2 - b^2)

Velocity modification: same formulas as inner core.

Temperature:
    R_outer = -2*b^2*ln(b) - r^2/2 + 2*b^2*ln(r) + b^4/(2*r^2)
    T = T_u - (gamma-1) * [v_m * a / (a^2 - b^2)]^2 * R_outer / (R*gamma)

**Pressure in vortex region (r <= b):**
    p = p_u * (T / T_u)^(gamma/(gamma-1))

### For r > b:
No vortex modification. Use upstream conditions directly.

*Note: Handle the coordinate singularity at r = 0 appropriately. The velocity
perturbation vanishes as r -> 0, but the thermodynamic modification does not.*

## Density

Throughout the domain, density is computed from the ideal gas law:
    rho = p / (R * T)

## Required Analysis

Generate the flow field on a structured grid of at least 400x400 points over the
domain [0,1]x[0,1]. Compute the following quantities and write them to
`/app/results/analysis.json`:

1. **shock_conditions**: Post-shock primitive variables and Mach number:
   - `rho_d`, `u_d`, `p_d`, `T_d`: downstream state from Rankine-Hugoniot
   - `M_d`: downstream Mach number = u_d / sqrt(gamma * R * T_d)

2. **conservation**: Total enthalpy H = c_p*T + (u^2 + v^2)/2 where c_p = gamma*R/(gamma-1):
   - `H_upstream`: total enthalpy in upstream far-field (away from vortex)
   - `H_downstream`: total enthalpy in downstream far-field
   - `relative_error`: |H_upstream - H_downstream| / H_upstream

3. **entropy**: Entropy defined as s = p / rho^gamma:
   - `s_upstream`: entropy in upstream far-field
   - `s_downstream`: entropy downstream of shock
   - `entropy_ratio`: s_downstream / s_upstream

4. **vortex_properties**:
   - `center_pressure`: pressure at vortex center (0.25, 0.5) — evaluate the
     flow field formulas at this exact point
   - `center_temperature`: temperature at vortex center
   - `center_density`: density at vortex center
   - `peak_vorticity`: peak vorticity magnitude in the vortex region
   - `circulation_r012`: circulation around the vortex at radius r = 0.12,
     defined as the line integral of velocity around a closed circular path

5. **field_statistics**: Computed from the 2D grid:
   - `max_mach`: maximum Mach number M = |v| / sqrt(gamma*p/rho) in the domain
   - `min_pressure`: minimum pressure in the domain
   - `max_vorticity`: maximum |omega| = |dv/dx - du/dy| computed from the grid
