#!/usr/bin/env python3
"""
Wire K14 scheme dispatch into the main driver program.
Adds the K14 module import and replaces the TODO stub with
the actual compute_k14_cell call.

"""

SRC = '/app/main.f90'

with open(SRC, 'r') as f:
    code = f.read()

# Add K14 module import
code = code.replace(
    '  use dust_physics_mod, only: compute_emission_cell',
    '  use dust_physics_mod, only: compute_emission_cell\n'
    '  use dust_k14_mod, only: compute_k14_cell'
)

# Replace K14 TODO with actual dispatch
code = code.replace(
    "      ! TODO: K14 scheme not implemented\n"
    "      write(0, '(A)') 'K14 scheme not yet available'\n"
    "      stop 1",
    "      call compute_k14_cell( &\n"
    "          wind_10m, rho_air, soil_moist_vol, &\n"
    "          clay_f, silt_f, sand_f, veg_frac, &\n"
    "          land_type, soil_type, &\n"
    "          out_ustar, out_uts0, out_fm, out_fr, &\n"
    "          out_z0, out_sep, out_hflux, out_alpha, &\n"
    "          out_vflux, out_emission)"
)

with open(SRC, 'w') as f:
    f.write(code)

print("K14 dispatch wired in main.f90")
