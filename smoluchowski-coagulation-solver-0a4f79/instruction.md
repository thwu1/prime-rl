Implement `/app/solve.py` that produces two artifacts: a shared library `/app/libcoag.so` and a results file `/app/results.nc`.

**Shared library (`/app/libcoag.so`):** A valid ELF shared object exporting these C-callable functions (all parameters `double`, passed by value, each returns `double`):

- `kernel_constant(vi, vj, beta0)`
- `kernel_additive(vi, vj, beta1)`
- `kernel_brownian(v1, rho1, v2, rho2, T, P)` -- coagulation kernel in m^3/s

Fortran 90 source defining the kernel physics is provided at `/app/reference/`. `gfortran` is available in the environment.

**Config:** `/app/config.json` defines a `scenarios` array. Each scenario has `name` and `kernel_type` (`"constant"`, `"additive"`, `"brownian_pairs"`, or `"brownian"`). Evolution scenarios include grid parameters, population parameters, and output times. The `"brownian_pairs"` scenario specifies radius pairs for direct kernel evaluation without time evolution. All units are SI.

**Output (`/app/results.nc`):** NetCDF4 file with groups named by scenario. Evolution groups (`constant`, `additive`, `brownian_evolve`) contain 1-D float64 variables `total_number`, `total_volume`, `mean_volume` on dimension `time` (one entry per element in the scenario's `times` array). Group `brownian_pairs` contains 1-D variable `kernel_values` on dimension `pair`.

**Acceptance criteria:**

*Library:* All three functions are exported dynamic symbols, callable via C ABI, producing correct values.

*Constant:* Initial N within 2% of N0. Subsequent N within 5% of expected values. N monotonically decreasing. Mean volume monotonically increasing. Volume conserved within 0.5%.

*Additive:* Initial N within 2% of N0. Subsequent N within 5% of expected values where those exceed 1000. Final/initial N ratio below 0.1. Volume conserved within 0.5%.

*Brownian pairs:* Correct count matching the number of input pairs. All values positive. Each within 2% of reference.

*Brownian evolution:* Initial N within 2% of N0. Volume conserved within 1%. N monotonically decreasing with at least 0.1% total decrease. Mean volume monotonically increasing.
