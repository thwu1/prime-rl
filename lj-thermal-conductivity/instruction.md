LAMMPS is pre-installed (`lmp`). System parameters and physical mapping constants for argon are in `/app/specification.json`.

Compute the thermal conductivity (kappa*) of the specified Lennard-Jones fluid at the given thermodynamic state point using two independent non-equilibrium molecular dynamics (NEMD) methods, and cross-validate them against each other. The two methods should each produce a spatial temperature profile data file in `/app/` named `profile.mp` and `profile.heat` respectively. Use an elongated simulation box with at least 20 spatial bins resolved along the heat-flux direction.

Convert the reduced-unit thermal conductivity values to SI units (W m^-1 K^-1) using the argon parameters provided in the specification file. Derive the appropriate conversion factor from the LJ unit system definitions.

Write all results to `/app/results.json` with these fields: `kappa_star_mp`, `kappa_star_heat`, `kappa_si_mp`, `kappa_si_heat`, `cross_validation_ratio` (max/min of the two kappa* values), and `conversion_factor_w_per_m_k` (the multiplicative factor from LJ to SI for thermal conductivity).