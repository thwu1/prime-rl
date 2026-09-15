A split-form DGSEM framework for the 1D compressible Euler equations is provided at `/app/`. The solver handles LGL quadrature, flux-differencing volume integrals with two-point volume fluxes, surface corrections, and SSP-RK3 time stepping, but three numerical flux functions in `/app/fluxes.py` are incomplete stubs that raise `NotImplementedError`.

A `Makefile` at `/app/Makefile` orchestrates the simulation and data-processing pipeline. Its `run` target executes the simulation driver. Two additional targets (`report` and `validate`) are stubs whose implementations must be completed using the specific command-line tools and output formats described in the Makefile's inline comments.

When all components are correctly implemented and the full pipeline is executed from `/app/`, the following files must be produced under `/app/results/`:

- `convergence.json` — mesh convergence data demonstrating near-optimal accuracy for the polynomial degree used
- `sod_solution.csv` — numerical solution of the Sod shock tube problem with physically correct wave structure
- `report.json` — convergence analysis summary derived from `convergence.json`
- `validation.txt` — physical correctness certification derived from `sod_solution.csv`

Working reference flux implementations (`lax_friedrichs_flux`, `central_flux`) in `/app/fluxes.py` illustrate the expected function interface. The mathematical requirements each stub must satisfy are documented in its docstring.