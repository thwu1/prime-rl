#!/usr/bin/env python3
"""
Fix all 6 physics bugs in dust_physics_mod.f90 by comparing the
implementation against the equations cited in each function's header.

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
# The cited Eq. (2) includes Gamma/(rho_a*D) inside the sqrt.
code = code.replace(
    'threshold_fric_vel = sqrt(A_N * (RHO_PARTICLE * GRAV * dp / rho_a))',
    'threshold_fric_vel = sqrt(A_N * (RHO_PARTICLE * GRAV * dp / rho_a'
    ' + GAMMA_COH / (rho_a * dp)))'
)

# --- Bug 2: Fecan moisture threshold coefficient ---
# Eq. (4): w' = 0.0014*(%clay)^2 + 0.17*(%clay), not 0.14.
code = code.replace(
    'w_prime = 0.14 * clay_pct * clay_pct + 0.17 * clay_pct',
    'w_prime = 0.0014 * clay_pct * clay_pct + 0.17 * clay_pct'
)

# --- Bug 3: Drag partition sign error ---
# Eq. (5): first factor is (1 - sig_V*m_V*lam_V), not (1 + ...).
code = code.replace(
    'fr_sq = (1.0 + SIG_V * M_V_PARAM * lambda_v)',
    'fr_sq = (1.0 - SIG_V * M_V_PARAM * lambda_v)'
)

# --- Bug 4a: Surface roughness critical lambda ---
# Eq. (8): transition at lambda = 0.2, not 0.045.
code = code.replace(
    'if (lambda_total < 0.045) then',
    'if (lambda_total < 0.2) then'
)

# --- Bug 4b: Surface roughness exponent sign ---
# Eq. (8): lambda^(-0.46) for the high-density branch, not lambda^(+0.46).
code = code.replace(
    'surface_roughness = 0.083 * lambda_total**0.46 * h_eff',
    'surface_roughness = 0.083 * lambda_total**(-0.46) * h_eff'
)

# --- Bug 5: White (1979) missing squared exponent ---
# Eq. (10): (1 + u*t/u*)^2, not (1 + u*t/u*).
code = code.replace(
    '* (1.0 - ut / ustar) * (1.0 + ut / ustar)',
    '* (1.0 - ut / ustar) * (1.0 + ut / ustar)**2'
)

# --- Bug 6: Lu-Shao (1999) missing u*-dependent term ---
# Eq. (13): alpha includes (0.24 + C_beta*u*sqrt(rho_p/p)), not just 0.24.
code = code.replace(
    'vert_horiz_ratio = ca * GRAV * ff * (RHO_BULK_LS / 2.0) / pp * 0.24',
    'vert_horiz_ratio = ca * GRAV * ff * (RHO_BULK_LS / 2.0) / pp'
    ' * (0.24 + cb * ustar * sqrt(RHO_PARTICLE / pp))'
)

with open(SRC, 'w') as f:
    f.write(code)

print("All 6 physics bugs fixed in dust_physics_mod.f90")
