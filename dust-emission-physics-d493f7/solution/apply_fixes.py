#!/usr/bin/env python3
"""Apply physics corrections to dust_physics.f90.

Fixes 5 implementation bugs and completes 4 unimplemented stubs
in the mineral dust emission physics module.
"""

import sys

with open('/app/dust_physics.f90', 'r') as f:
    code = f.read()

original = code
fix_count = 0


def apply_fix(code, old, new, name):
    """Apply a single string replacement, verifying the pattern exists."""
    global fix_count
    if old not in code:
        print(f"ERROR: {name}: pattern not found in source", file=sys.stderr)
        sys.exit(1)
    code = code.replace(old, new, 1)
    fix_count += 1
    print(f"Applied {name}")
    return code


# ----------------------------------------------------------------
# Fix 1: Implement threshold_ustar (Shao & Lu 2000)
# The stub returns 0.0; implement:
#   u*t0 = sqrt(A_N * (rho_p*g*D/rho_a + Gamma/(rho_a*D)))
# ----------------------------------------------------------------
code = apply_fix(code,
    '    ust0 = 0.0d0\n\n  end function threshold_ustar',
    '    ust0 = sqrt(A_N * (rho_p * GRAV * Dp / rho_a &\n'
    '         + GAMMA_COHESION / (rho_a * Dp)))\n\n'
    '  end function threshold_ustar',
    'Fix 1: threshold_ustar')

# ----------------------------------------------------------------
# Fix 2: Fecan moisture correction - missing squared term
# Bug: w_prime = 0.0014*clay + 0.17*clay  (linear)
# Fix: w_prime = 0.0014*clay^2 + 0.17*clay (quadratic)
# ----------------------------------------------------------------
code = apply_fix(code,
    'w_prime = 0.0014d0 * clay_pct + 0.17d0 * clay_pct',
    'w_prime = 0.0014d0 * clay_pct**2 + 0.17d0 * clay_pct',
    'Fix 2: Fecan moisture')

# ----------------------------------------------------------------
# Fix 3: Drag partition - wrong normalization constant
# Bug: uses 0.1 (King/Darmenova alternative)
# Fix: use 122.55 (MacKinnon et al. 2004)
# ----------------------------------------------------------------
code = apply_fix(code,
    'log(0.7d0 * (0.1d0/z0s)**0.8d0)',
    'log(0.7d0 * (122.55d0/z0s)**0.8d0)',
    'Fix 3: Drag partition')

# ----------------------------------------------------------------
# Fix 4: White (1979) saltation flux - missing factor
# Bug: uses u* only (Owen 1964 formula)
# Fix: use (u* + u*t) (White 1979 formula)
# ----------------------------------------------------------------
code = apply_fix(code,
    'FH = (rho_a / GRAV) * ustar * (ustar**2 - ustar_t**2)',
    'FH = (rho_a / GRAV) * (ustar + ustar_t) * (ustar**2 - ustar_t**2)',
    'Fix 4: White79 saltation')

# ----------------------------------------------------------------
# Fix 5: K14 emission coefficient - wrong variable in exponential
# Bug: C_d = C_D0 * exp(-C_E * u_st)
# Fix: C_d = C_D0 * exp(-C_E * f_ust)
# ----------------------------------------------------------------
code = apply_fix(code,
    'C_d = C_D0 * exp(-C_E_K14 * u_st)',
    'C_d = C_D0 * exp(-C_E_K14 * f_ust)',
    'Fix 5: K14 coefficient')

# ----------------------------------------------------------------
# Fix 6: Foroutan roughness - swapped regime formulas
# Bug: lambda < 0.2 uses high-lambda formula and vice versa
# Fix: swap so lambda < 0.2 gets 0.96*lambda^1.07
# ----------------------------------------------------------------
code = apply_fix(code,
    "    if (lambda < 0.2d0) then\n"
    "      z0_over_h = 0.083d0 * lambda**(-0.46d0)\n"
    "    else\n"
    "      z0_over_h = 0.96d0 * lambda**(1.07d0)\n"
    "    end if",
    "    if (lambda < 0.2d0) then\n"
    "      z0_over_h = 0.96d0 * lambda**(1.07d0)\n"
    "    else\n"
    "      z0_over_h = 0.083d0 * lambda**(-0.46d0)\n"
    "    end if",
    'Fix 6: Foroutan regime')

# ----------------------------------------------------------------
# Fix 7: Implement erodibility_factor (Laurent et al. 2008)
# The stub returns 1.0; implement full branching logic.
# ----------------------------------------------------------------
code = apply_fix(code,
    "    f_erod = 1.0d0\n"
    "\n"
    "  end function erodibility_factor",
    "    if (is_bedrock) then\n"
    "      f_erod = 0.0d0\n"
    "      return\n"
    "    end if\n"
    "\n"
    "    if (z0 <= 3.0d-5) then\n"
    "      f_erod = 1.0d0\n"
    "    else if (z0 < Z0_MAX) then\n"
    "      f_erod = max(0.0d0, 0.7304d0 - 0.0804d0 * log10(100.0d0 * z0))\n"
    "    else\n"
    "      f_erod = 0.0d0\n"
    "    end if\n"
    "\n"
    "  end function erodibility_factor",
    'Fix 7: Erodibility')

# ----------------------------------------------------------------
# Fix 8a: Implement kok2011_size_fraction body
# Uses inline Simpson's rule integration (n=1000) calling a
# module-level helper function kok_integrand_fn (added in fix 8b).
# This avoids internal-subprogram-calling-internal-subprogram
# patterns that can be unreliable in some compilers.
# ----------------------------------------------------------------
code = apply_fix(code,
    "    frac = 0.0d0\n"
    "\n"
    "  end function kok2011_size_fraction",
    "    double precision :: num, den, h_int, s_val\n"
    "    integer :: ii\n"
    "    integer, parameter :: N_SIMP = 1000\n"
    "\n"
    "    ! Numerator: Simpson's rule over [D_low, D_high]\n"
    "    h_int = (D_high - D_low) / dble(N_SIMP)\n"
    "    s_val = kok_integrand_fn(D_low) + kok_integrand_fn(D_high)\n"
    "    do ii = 1, N_SIMP - 1, 2\n"
    "      s_val = s_val + 4.0d0 * kok_integrand_fn(D_low + dble(ii) * h_int)\n"
    "    end do\n"
    "    do ii = 2, N_SIMP - 2, 2\n"
    "      s_val = s_val + 2.0d0 * kok_integrand_fn(D_low + dble(ii) * h_int)\n"
    "    end do\n"
    "    num = s_val * h_int / 3.0d0\n"
    "\n"
    "    ! Denominator: Simpson's rule over full bin range\n"
    "    h_int = (BIN_BOUNDS(6) - BIN_BOUNDS(1)) / dble(N_SIMP)\n"
    "    s_val = kok_integrand_fn(BIN_BOUNDS(1)) + kok_integrand_fn(BIN_BOUNDS(6))\n"
    "    do ii = 1, N_SIMP - 1, 2\n"
    "      s_val = s_val + 4.0d0 * kok_integrand_fn(BIN_BOUNDS(1) + dble(ii) * h_int)\n"
    "    end do\n"
    "    do ii = 2, N_SIMP - 2, 2\n"
    "      s_val = s_val + 2.0d0 * kok_integrand_fn(BIN_BOUNDS(1) + dble(ii) * h_int)\n"
    "    end do\n"
    "    den = s_val * h_int / 3.0d0\n"
    "\n"
    "    if (den > 0.0d0) then\n"
    "      frac = num / den\n"
    "    else\n"
    "      frac = 0.0d0\n"
    "    end if\n"
    "\n"
    "  end function kok2011_size_fraction",
    'Fix 8a: Kok2011 body')

# ----------------------------------------------------------------
# Fix 8b: Add kok_integrand_fn as private module-level procedure
# Placed before 'end module' so all module procedures can call it.
# Uses module constants D_S_KOK, SIGMA_S, LAMBDA_K directly.
# ----------------------------------------------------------------
code = apply_fix(code,
    "end module dust_physics",
    "\n"
    "  ! Private helper: Kok (2011) mass size distribution integrand\n"
    "  ! g(D) = (1/D) * [1 + erf(ln(D/Ds)/(sqrt(2)*sigma))] * exp(-(D/lambda)^3)\n"
    "  double precision function kok_integrand_fn(D) result(gD)\n"
    "    double precision, intent(in) :: D\n"
    "    double precision :: la\n"
    "    la = log(D / D_S_KOK) / (sqrt(2.0d0) * SIGMA_S)\n"
    "    gD = (1.0d0 / D) * (1.0d0 + erf(la)) * exp(-(D / LAMBDA_K)**3)\n"
    "  end function kok_integrand_fn\n"
    "\n"
    "end module dust_physics",
    'Fix 8b: Add integrand function')

# ----------------------------------------------------------------
# Fix 9: Implement compute_cell_emission
# Orchestrates the coupled emission pipeline:
#   threshold(D_CHAR) -> grav moisture -> Fecan -> drag partition
#   -> soil u* -> effective threshold -> erodibility -> K14 flux
#   -> per-bin split via Kok size fractions
# ----------------------------------------------------------------
code = apply_fix(code,
    "    emissions = 0.0d0\n"
    "    rc = 0\n"
    "\n"
    "  end subroutine compute_cell_emission",
    "    double precision :: ust0, w_pct, fm, R_dp, u_soil, u_thresh\n"
    "    double precision :: f_erod, k_gamma, F_total\n"
    "    integer :: i\n"
    "\n"
    "    rc = 0\n"
    "    emissions = 0.0d0\n"
    "\n"
    "    ust0 = threshold_ustar(D_CHAR, rho_p, rho_a)\n"
    "    w_pct = gravimetric_moisture(w_vol, sand_frac, f_w)\n"
    "    fm = fecan_moisture_correction(w_pct, clay_frac * 100.0d0)\n"
    "    R_dp = drag_partition_mackinnon(z0, z0s)\n"
    "    u_soil = R_dp * ustar_in\n"
    "    u_thresh = ust0 * fm\n"
    "    f_erod = erodibility_factor(z0, is_bedrock)\n"
    "    k_gamma = clay_frac\n"
    "    F_total = k14_vertical_flux(u_soil, u_thresh, rho_a, f_erod, k_gamma)\n"
    "\n"
    "    do i = 1, N_BINS\n"
    "      emissions(i) = F_total &\n"
    "                   * kok2011_size_fraction(BIN_BOUNDS(i), BIN_BOUNDS(i+1))\n"
    "    end do\n"
    "\n"
    "  end subroutine compute_cell_emission",
    'Fix 9: Cell emission pipeline')

# ----------------------------------------------------------------
# Verification
# ----------------------------------------------------------------
if code == original:
    print("ERROR: No changes were made!", file=sys.stderr)
    sys.exit(1)

# Spot-check that key patterns exist in the corrected code
checks = [
    ('GAMMA_COHESION / (rho_a * Dp)', 'threshold_ustar formula'),
    ('clay_pct**2', 'Fecan squared term'),
    ('122.55d0', 'MacKinnon constant'),
    ('(ustar + ustar_t)', 'White79 factor'),
    ('exp(-C_E_K14 * f_ust)', 'K14 exponential'),
    ('0.96d0 * lambda**(1.07d0)', 'Foroutan low-lambda'),
    ('is_bedrock', 'bedrock check'),
    ('kok_integrand_fn', 'Kok integrand calls'),
    ('F_total', 'pipeline total flux'),
]
for pattern, desc in checks:
    if pattern not in code:
        print(f"ERROR: Verification failed - missing '{desc}'", file=sys.stderr)
        sys.exit(1)

with open('/app/dust_physics.f90', 'w') as f:
    f.write(code)

print(f"\nAll {fix_count} replacements applied and verified in dust_physics.f90")
