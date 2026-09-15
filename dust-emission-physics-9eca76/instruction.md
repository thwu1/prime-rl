A Fortran program at `/app/` computes windblown mineral dust emission fluxes using two selectable schemes: FENGSHA (Foroutan et al. 2017) and K14 (Kok et al. 2014). Build with `make -C /app`. The executable `/app/dust_emission` reads scenario data from stdin and writes diagnostic output to stdout.

The FENGSHA physics module `/app/dust_physics_mod.f90` contains functions with header comments citing specific published equations. The current implementation produces incorrect results due to deviations from these cited equations.

The K14 physics module `/app/dust_k14_mod.f90` has function stubs returning zero, each with a header comment citing the equation to implement. All K14 functions and the K14 cell-computation subroutine must be implemented. The K14 module must import shared physics functions (threshold friction velocity, moisture correction, surface roughness, vegetation roughness density, volumetric-to-gravimetric moisture conversion) from the FENGSHA module; those functions are currently private and must be made public.

The driver `/app/main.f90` handles FENGSHA dispatch but the K14 code path is stubbed out and must be completed.

Fix the FENGSHA module, implement all K14 functions, and complete the driver so both schemes produce physically correct output.

Input format (stdin):
```
<scheme>
<n_cells>
<wind_10m> <rho_air> <soil_moist_vol> <clay_f> <silt_f> <sand_f> <veg_frac> <land_type> <soil_type>
```

`scheme` is `fengsha` or `k14`. Fractions in [0,1]. `land_type` (1=shrubland, 2=shrubgrass, 3=barren, 4=cropland). `soil_type` (1=sand, 2=loam, 3=sandy_clay_loam, 4=clay). Volumetric soil moisture in m^3/m^3.

Output format (stdout): header line then one data line per cell, space-separated, scientific notation, SI units:
```
cell_id u_star u_ts0 f_moist f_rough z0 sep h_flux alpha v_flux emission
```

Column semantics differ by scheme:
- FENGSHA: `f_rough`=Raupach drag partition, `sep`=soil erodibility, `h_flux`=horizontal saltation flux, `alpha`=Lu-Shao vertical/horizontal ratio
- K14: `f_rough`=MacKinnon drag partition R, `sep`=clay-silt parameter k_gamma, `h_flux`=aeolian friction velocity (R*u_star), `alpha`=Kok emission coefficient C_d

Test scenarios at `/app/scenarios/test_fengsha.txt` and `/app/scenarios/test_k14.txt`.

Requirements:
- Compiles cleanly with `make -C /app`
- All output columns match cited parameterizations within 2% relative tolerance for all scenarios in both schemes
- Zero emission when wind is below mobilization threshold in both schemes
- Both schemes must be runnable from a single executable via the scheme selector in the input
