The directory `/app/pr_eos/` contains a Python package implementing the Peng-Robinson cubic equation of state for multicomponent vapor-liquid equilibrium calculations. The cubic equation solver is implemented as a C shared library in `/app/libcubic/`, loaded via `ctypes`. The implementation chain produces incorrect thermodynamic results due to multiple interacting defects spanning the build system, C source, and Python modules.

Validated reference data for several chemical systems is provided as JSON files in `/app/reference_data/`.

Diagnose and repair all defects, then deliver:

`/app/libcubic/libcubic.so` — Compiled from corrected source via `make -C /app/libcubic`. Must export `int solve_cubic_eos(double A, double B, double roots[3])` which solves the PR EOS compressibility-factor cubic given dimensionless parameters A and B, returning the count of real Z-roots sorted ascending.

`/app/pr_mix.py` — Python module (stdlib only: `math`, `sys`, `ctypes`, `os`) that loads `/app/libcubic/libcubic.so` for cubic solving and exports:

- `mixture_fugacity_coefficients(T, P, zs, Tcs, Pcs, omegas, kijs, phase)` — Fugacity coefficients list. `phase` is `'liquid'` (smallest volume root where V > b) or `'vapor'` (largest).
- `rachford_rice(zs, Ks)` — Equilibrium vapor fraction VF in [0, 1].
- `flash_pt(T, P, zs, Tcs, Pcs, omegas, kijs)` — Returns `{'VF': float, 'xs': list, 'ys': list}`.

`/app/flash_cli.py` — Reads a JSON file path from `sys.argv[1]` with keys `T, P, zs, Tcs, Pcs, omegas, kijs`. Prints JSON to stdout with keys `VF, xs, ys, phis_l, phis_g`.

**Acceptance criteria:**
- `make -C /app/libcubic` compiles `libcubic.so` without errors; the library is loadable via `ctypes.CDLL`
- Z-roots returned by `solve_cubic_eos` must satisfy the original cubic equation to 1e-8 residual
- Fugacity coefficients within 5e-4 relative tolerance of reference values
- Flash compositions and vapor fractions within 5e-3 relative tolerance
- Component fugacities equal across phases to 1e-3 relative tolerance at equilibrium
- Material balance closure: z_i = x_i*(1-VF) + y_i*VF for all components
