The C project at `/app/` implements a seawater thermodynamics pipeline following the TEOS-10 (Thermodynamic Equation of Seawater 2010) standard. It processes oceanographic CTD cast data — Absolute Salinity (SA), Conservative Temperature (CT), sea pressure (p), and pre-computed gravity — to compute derived quantities.

Build: `make -C /app`
Run: `/app/ctd_pipeline`

The code compiles and runs, but produces incorrect results. Fix `/app/gsw_pipeline.c` so that all computed values are numerically accurate according to the TEOS-10 specification.

**Required output** (`/app/output.json`): JSON object with arrays:
- `specvol` — specific volume (m³/kg)
- `rho` — in-situ density (kg/m³)
- `alpha` — thermal expansion coefficient (1/K)
- `beta` — haline contraction coefficient (kg/g)
- `sigma0` — potential density anomaly referenced to 0 dbar (kg/m³)
- `n2` — buoyancy frequency squared (rad²/s²)
- `p_mid_n2` — mid-level pressures for N² (dbar)

Input points marked with the sentinel value 9×10⁹⁰ must be excluded from output arrays.

**Constraints**:
- Only modify files under `/app/`. Do not modify test files.
- The implementation must produce correct results for arbitrary valid oceanographic inputs, not just the built-in dataset.

**Success criteria**: All output values must match the TEOS-10 reference implementation to its published precision. Internet access is available.
