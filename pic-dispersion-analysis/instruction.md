WarpX particle-in-cell simulation input files are provided in `/app/simulations/`. Reference documentation for the WarpX input format and physical constants is available in `/app/docs/`.

Analyze each simulation's electromagnetic grid configuration and produce a numerical stability and dispersion audit. Write the results to `/app/audit_report.json` as a JSON object keyed by simulation name (the portion of each input filename after `inputs_`).

Each simulation entry must contain these sections:

**`grid`**: `dx_m`, `dy_m`, `dz_m` (cell sizes, meters), `total_cells` (integer product of all cell counts).

**`timestep`**: `dt_s` (stability-limited time step for the 3D FDTD scheme, seconds), `cfl_factor` (configured safety factor).

**`laser`**: `wavelength_m`, `frequency_rad_s`, `wavenumber_1m`, `peak_field_Vm`, `normalized_amplitude` (dimensionless), `peak_intensity_Wcm2`, `rayleigh_length_m`.

**`plasma`**: `density_m3` (electron density), `frequency_rad_s`, `wavelength_m`, `skin_depth_m`, `critical_density_m3`, `density_ratio`, `wavebreaking_field_Vm`.

**`resolution`**: `cells_per_laser_wavelength` (propagation direction), `cells_per_skin_depth` (finest transverse resolution), `cells_per_plasma_wavelength` (propagation direction).

**`numerical_dispersion`**: `phase_error_pct` and `group_error_pct` -- percent deviation of the FDTD numerical phase and group velocities from c, evaluated for a monochromatic plane wave at the laser wavenumber propagating along z.

**`verdict`**: `cfl_stable` (boolean) and `well_resolved` (boolean -- true when there are at least 8 cells per laser wavelength and at least 1 cell per skin depth).

All floating-point values must be accurate to at least 6 significant figures.