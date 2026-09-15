The file `/app/coolprop_co2.json` is a CoolProp-format fluid definition for CO2 containing equation-of-state coefficients, ancillary correlations, transport data, and metadata. The file `/app/cycle_params.json` specifies operating conditions for a single-stage transcritical CO2 refrigeration cycle. NIST WebBook reference data is provided in `/app/nist_co2_saturation.csv`, `/app/nist_co2_350K.csv`, and `/app/nist_co2_8MPa.tsv`.

**Required: `/app/Makefile`** with these targets:

- `extract` — use `jq` to parse `/app/coolprop_co2.json` and produce `/app/co2_coefficients.json` containing only the fields needed by the EOS implementation: gas constant, molar mass, reducing-state parameters, acentric factor, and the ideal-gas and residual coefficient arrays, preserving their original structure
- `compute` — run the cycle computation, producing `/app/results.json`
- `diagram` — use `gnuplot` to render `/app/ph_diagram.png`: pressure (MPa, log scale) on y-axis, specific enthalpy (kJ/kg) on x-axis, with the four cycle state points labeled 1-4 and connected by lines
- `all` (default) — runs extract, compute, diagram in dependency order

**Required: `/app/co2_eos.py`**

Python module with these functions using SI molar units (T in K, rho in mol/m^3, P in Pa, h in J/mol, s/cv/cp in J/(mol*K), w in m/s):

- `pressure(T, rho)`, `enthalpy(T, rho)`, `entropy(T, rho)`, `cv(T, rho)`, `cp(T, rho)`, `speed_of_sound(T, rho)` — enthalpy and entropy use IIR reference state
- `saturation_pressure(T)` — for T below critical temperature
- `saturation_densities(T)` — returns `(rho_liquid, rho_vapor)` in mol/m^3
- `density(T, P, phase)` — phase is `"liquid"`, `"vapor"`, or `"supercritical"`

All properties must match NIST WebBook values to within 0.1% across subcritical and supercritical regions. External thermodynamic property libraries (CoolProp, REFPROP, thermo, chemicals, fluids, pyromat) are prohibited.

**Required: `/app/compute_cycle.py`**

Reads `/app/cycle_params.json`, computes the cycle, and writes `/app/results.json`:
```json
{
  "P_evap_Pa": <float>,
  "state1": {"T_K": <float>, "P_Pa": <float>, "rho_mol_m3": <float>, "h_J_mol": <float>, "s_J_molK": <float>},
  "state2": {"T_K": <float>, "P_Pa": <float>, "rho_mol_m3": <float>, "h_J_mol": <float>, "s_J_molK": <float>},
  "state3": {"T_K": <float>, "P_Pa": <float>, "rho_mol_m3": <float>, "h_J_mol": <float>, "s_J_molK": <float>},
  "COP_cooling": <float>,
  "COP_heating": <float>,
  "compressor_work_J_mol": <float>
}
```

**Required: `/app/ph_diagram.png`** — gnuplot-rendered pressure-enthalpy diagram of the cycle as described above.
