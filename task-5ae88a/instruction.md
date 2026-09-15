A 2D compressible Euler finite volume solver is at `/app/euler_fv.py`. It uses a second-order Godunov method with Rusanov fluxes on a uniform periodic grid. Initial conditions for a magnetized vortex problem are in `/app/initial_conditions.h5` (containing density, velocity, gas pressure, and face-centered magnetic field arrays). Parameters are in `/app/config.json`.

Extend this solver to the **ideal MHD equations** with fully coupled magnetic fields and produce:

- `/app/mhd_solver.py` — reads `/app/initial_conditions.h5`, evolves the ideal MHD system to `tEnd`, writes all outputs below. Must maintain max |div(B)| < 1e-10 throughout the simulation and conserve mass, total energy, and momentum.

- `/app/results.json` — keys: `total_mass`, `total_energy`, `total_momx`, `total_momy`, `max_divB`, `max_density`, `min_density`, `mean_density`, `magnetic_energy`, `kinetic_energy`, `internal_energy`, `num_steps`. Energy definitions (cell-centered values, cell volume dx^2):
  - `magnetic_energy = sum((Bx^2 + By^2)/2 * dx^2)`
  - `kinetic_energy = sum(rho*(vx^2 + vy^2)/2 * dx^2)`
  - `internal_energy = sum(P_gas/(gamma-1) * dx^2)`

- `/app/density_final.dat` — final density as space-delimited NxN text matrix.

- `/app/density_contour.png` — filled contour or heatmap of final density via gnuplot.

- `/app/Makefile` — targets: `run` (executes solver), `plot` (generates PNG from density data via gnuplot), `all` (both in sequence).