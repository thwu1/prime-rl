A Rust project at `/app/` contains a skeleton PC-SAFT (Perturbed-Chain Statistical Associating Fluid Theory) equation of state for pure non-associating components. The file `/app/src/lib.rs` provides universal model constants (A0--A2, B0--B2), parameter definitions for propane/butane/methane, and function stubs marked `todo!()`. The file `/app/src/main.rs` exercises the library and writes computed thermodynamic properties to `/app/results.json`.

Complete all `todo!()` stubs in `/app/src/lib.rs` so that `cd /app && cargo run --release` produces `/app/results.json` with physically correct values.

**Required `/app/results.json` schema:**
```json
{
  "a_hs_x_v": <float>,
  "a_hc_x_v": <float>,
  "a_disp_x_v": <float>,
  "tc_kelvin": <float>,
  "rhoc_mol_m3": <float>,
  "psat_ratio": <float>,
  "fugacity_diff": <float>
}
```

**Field definitions:**
- `a_hs_x_v`, `a_hc_x_v`, `a_disp_x_v`: Hard-sphere, hard-chain, and dispersion reduced Helmholtz energy density contributions multiplied by volume at reference state (T=250 K, V=1000 A^3, N=1 particle, propane).
- `tc_kelvin`: Pure propane critical temperature in Kelvin.
- `rhoc_mol_m3`: Pure propane critical molar density in mol/m^3.
- `psat_ratio`: Ratio P_vapor/P_liquid at the converged VLE for propane at T=300 K.
- `fugacity_diff`: Absolute difference in total chemical potential mu/(kT) between vapor and liquid phases at VLE.

**Acceptance criteria:**
- Helmholtz energy contributions match reference values within 1e-4 relative tolerance.
- Critical temperature within 0.5 K of reference; critical density within 1%.
- VLE pressure ratio within 1e-4 of unity; fugacity difference below 1e-3.

**Build command:** `cd /app && cargo build --release && cargo run --release`

Function docstrings in `/app/src/lib.rs` specify the thermodynamic definitions for each contribution. No external Rust crates are required.
