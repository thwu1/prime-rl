#!/usr/bin/env python3
"""
Fix all 6 physics bugs in dust_physics_mod.f90 by comparing the
implementation against the equations cited in each function's header.
Also exports shared physics functions so the K14 module can use them.

Each fix corrects a deviation from the published formula:
  1. Shao-Lu (2000) threshold: missing interparticle cohesion term
  2. Fecan (1999) moisture: wrong coefficient (0.14 vs 0.0014)
  3. Drag partition (Eq. 5): sign error in first vegetation factor
  4. Foroutan (2017) roughness: wrong critical lambda and exponent sign
  5. White (1979) flux: missing squared exponent on (1+u*t/u*) term
  6. Lu-Shao (1999) ratio: missing u*-dependent term in alpha

"""

SRC = '/app/dust_physics_mod.f90'

with open(SRC, 'r') as f:
    code = f.read()

# --- Bug 1: Shao-Lu threshold velocity missing cohesion term ---
code = code.replace(
    'threshold_fric_vel = sqrt(A_N * (RHO_PARTICLE * GRAV * dp / rho_a))',
    'threshold_fric_vel = sqrt(A_N * (RHO_PARTICLE * GRAV * dp / rho_a'
    ' + GAMMA_COH / (rho_a * dp)))'
)

# --- Bug 2: Fecan moisture threshold coefficient ---
code = code.replace(
    'w_prime = 0.14 * clay_pct * clay_pct + 0.17 * clay_pct',
    'w_prime = 0.0014 * clay_pct * clay_pct + 0.17 * clay_pct'
)

# --- Bug 3: Drag partition sign error ---
code = code.replace(
    'fr_sq = (1.0 + SIG_V * M_V_PARAM * lambda_v)',
    'fr_sq = (1.0 - SIG_V * M_V_PARAM * lambda_v)'
)

# --- Bug 4a: Surface roughness critical lambda ---
code = code.replace(
    'if (lambda_total < 0.045) then',
    'if (lambda_total < 0.2) then'
)

# --- Bug 4b: Surface roughness exponent sign ---
code = code.replace(
    'surface_roughness = 0.083 * lambda_total**0.46 * h_eff',
    'surface_roughness = 0.083 * lambda_total**(-0.46) * h_eff'
)

# --- Bug 5: White (1979) missing squared exponent ---
code = code.replace(
    '* (1.0 - ut / ustar) * (1.0 + ut / ustar)',
    '* (1.0 - ut / ustar) * (1.0 + ut / ustar)**2'
)

# --- Bug 6: Lu-Shao (1999) missing u*-dependent term ---
code = code.replace(
    'vert_horiz_ratio = ca * GRAV * ff * (RHO_BULK_LS / 2.0) / pp * 0.24',
    'vert_horiz_ratio = ca * GRAV * ff * (RHO_BULK_LS / 2.0) / pp'
    ' * (0.24 + cb * ustar * sqrt(RHO_PARTICLE / pp))'
)

# --- Export shared functions for K14 module ---
code = code.replace(
    '  public :: compute_emission_cell',
    '  public :: compute_emission_cell\n'
    '  public :: threshold_fric_vel, moisture_factor\n'
    '  public :: veg_roughness_density, surface_roughness\n'
    '  public :: vol_to_grav_moisture'
)

with open(SRC, 'w') as f:
    f.write(code)

print("All 6 physics bugs fixed, shared functions exported.")
