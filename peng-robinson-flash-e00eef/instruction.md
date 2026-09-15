A Peng-Robinson (1976) equation of state engine must be completed in Rust at `/app/`. The project contains `Cargo.toml`, component parameters at `/app/data/components.json`, and `/app/src/main.rs` with data structures, partial helper implementations, and function stubs.

The program must read component parameters from `/app/data/components.json` (fields: `name`, `tc` K, `pc` Pa, `omega`, `molarweight` g/mol), compute the quantities below, and write a JSON object to `/app/results.json`:

**Pure component saturation pressures:**
- `propane_psat_300K_Pa`: Propane at T = 300 K (Pa).
- `butane_psat_350K_Pa`: Butane at T = 350 K (Pa).

**Binary mixture VLE -- propane(1)/butane(2), T = 300 K, van der Waals one-fluid mixing rules, all k\_ij = 0:**
- `propane_butane_bubble_300K_Pa`: Bubble-point pressure for liquid mole fractions x = [0.4, 0.6] (Pa).
- `propane_butane_dew_300K_Pa`: Dew-point pressure for vapor mole fractions y = [0.4, 0.6] (Pa).

**Ternary isothermal flash -- propane(1)/butane(2)/pentane(3), T = 300 K, P = 250 000 Pa, z = [0.2, 0.3, 0.5], all k\_ij = 0:**
- `flash_vapor_fraction`: Vapor fraction beta.
- `flash_liquid_composition`: Liquid mole fractions [x1, x2, x3].
- `flash_vapor_composition`: Vapor mole fractions [y1, y2, y3].

**Thermodynamic departure properties -- propane at T = 300 K, evaluated at saturation:**
- `propane_hvap_300K_J_per_mol`: Molar enthalpy of vaporization (J/mol).
- `propane_z_liq_300K`: Liquid-phase compressibility factor Z.
- `propane_cv_res_liq_300K_J_per_molK`: Residual isochoric heat capacity of the liquid phase (J/(mol K)), derived from the equation of state second temperature derivative of the Helmholtz energy.

Use R = 8.31446261815324 J/(mol K). Build and run: `cd /app && cargo build --release && cargo run --release`. The binary must exit 0 and produce `/app/results.json`.

Tolerances: vapor pressures, bubble-point, and dew-point within 0.1% relative; flash compositions sum to 1.0 within 1e-3 and match reference within 0.5%; enthalpy of vaporization within 0.5%; compressibility factor within 0.1%; residual Cv within 1%.

Existing code in the skeleton may contain errors that must be identified and corrected.
