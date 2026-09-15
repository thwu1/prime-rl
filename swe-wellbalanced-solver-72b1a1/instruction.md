A multi-layer 1D shallow water equation (Saint-Venant) solver pipeline at `/app/` is broken across its C shared library, build system, Python-C FFI bindings, numerical methods, and output formatting. Fix all defects so every scenario passes validation.

**Build pipeline**: `make -C /app` must compile `/app/src/flux_kernels.c` into `/app/lib/libflux.so`. The shared library exports `hll_flux(double h_L, double h_R, double hu_L, double hu_R, double g, double* F_h, double* F_hu)`.

**Python solver** — `/app/swe1d.py` must expose:

- `solve(scenario: str) -> dict` — scenario is one of `"lake_at_rest"`, `"dam_break_dry"`, `"dam_break_wet"`, `"subcritical_bump"`, `"transcritical_shock"`. Returns dict with keys `"x"`, `"h"`, `"u"`, `"eta"` (NumPy arrays) and `"t_final"` (float). `eta` must equal `h + z_b`. All `h` values must be non-negative. The solver must call the compiled C library for flux computation via `ctypes`. Array lengths: 200 for bump-topography scenarios, 500 for dam-break scenarios.

- `parse_params(filepath: str) -> dict` — reads `/app/params/<scenario>.dat` files. Format: one key per line, value on the next line; `#`-prefixed lines are comments. Returns flat dict: numeric values as `float`, non-numeric as `str`. Every file contains `GravityAcceleration` (9.81).

**HDF5 output** — Each call to `solve` must write `/app/output/<scenario>.h5` containing datasets `/x`, `/h`, `/u`, `/eta` (1D float64 arrays), `/t_final` (scalar float64), and a `gravity` attribute on the root group.

**CLI mode** — `python3 /app/swe1d.py <scenario>` writes the HDF5 file and prints JSON to stdout with keys `"x"`, `"h"`, `"u"`, `"eta"` (lists) and `"t_final"` (float). Exit code 0.

**Validation tolerances** (all five must pass simultaneously):

| Scenario | Criteria |
|---|---|
| `lake_at_rest` | L-inf(eta − 0.5) < 1e-10; L-inf(u) < 1e-10; eta and h + z_b agree to atol 1e-12 |
| `dam_break_dry` | L2 rel. depth error < 5% on wet cells (h > 0.01); mass conserved to 1%; wet front within 2 m of exact position |
| `dam_break_wet` | L2 rel. depth error < 5%; shock captured (min cell-to-cell Δh < −0.1); undisturbed upstream h > 4.5 preserved |
| `subcritical_bump` | L2 rel. eta error < 1%; discharge q mean ≈ 4.42 (±0.2), std < 0.15; Froude < 1 everywhere |
| `transcritical_shock` | L2 rel. eta error < 5%; supercritical region near crest (Fr > 1); hydraulic jump downstream (max Δh > 0.05); discharge q mean ≈ 0.18 (±0.02), std < 0.02 on wet cells |
