Build `/app/electrolyte_engine.py`, a CLI tool for thermodynamic analysis of aqueous electrolyte mixtures using pyEQL.

Accepts `--input <path>` and `--output <path>`.

**Input JSON schema:**

```json
{
  "solutions": [
    {"name": "<str>", "solutes": {"<formula>": "<conc>"}, "pH": <float>,
     "temperature": "<pint>", "volume": "<pint>"}
  ],
  "scan_steps": <int>,
  "concentration_profile": {
    "salt_cation": "<formula>", "salt_anion": "<formula>",
    "min_molal": <float>, "max_molal": <float>, "steps": <int>
  },
  "target_water_activity": <float>
}
```

Formulas follow pyEQL conventions (`"Na+"`, `"Ca+2"`, `"SO4-2"`). Concentrations are pint-compatible strings. Empty `solutes` means pure water. `concentration_profile` and `target_water_activity` are optional; include those output sections only when present in input.

**Output JSON schema:**

```json
{
  "individual": [{"name": "<str>", "ionic_strength_mol_kg": <f>, "conductivity_S_m": <f>,
    "density_kg_L": <f>, "osmotic_pressure_Pa": <f>, "water_activity": <f>, "pH": <f>,
    "hardness_mg_L": <f>, "debye_length_nm": <f>,
    "activity_coefficients": {"<species>": <f>}}],
  "blend": {"<same fields without name>"},
  "thermodynamics": {"gibbs_mix_J": <f>, "gibbs_mix_ideal_J": <f>,
    "entropy_mix_J_K": <f>, "nonideality_factor": <f>,
    "min_energy_separation_kWh_m3": <f>,
    "excess_volume_mL": <f>, "excess_gibbs_J": <f>},
  "scan": [{"fraction_0": <f>, "gibbs_mix_J": <f>, "optimal": <bool>}],
  "concentration_profile": {"points": [{"molality": <f>, "gamma_mean": <f>,
    "debye_length_nm": <f>}], "gamma_minimum": {"molality": <f>, "value": <f>},
    "gamma_unity_crossing_molality": "<f or null>"},
  "dilution": {"dilution_volume_L": <f>, "achieved_water_activity": <f>,
    "diluted_ionic_strength_mol_kg": <f>}
}
```

**Requirements:**

- `activity_coefficients`: each solute (excluding water, H+, OH-) mapped to its molal-scale activity coefficient. Must match published reference data for common electrolytes (e.g., NaCl at various concentrations) to within 6%.
- `debye_length_nm`: Debye screening length in nanometers.
- `blend`: full mixture of all input solutions at their specified volumes. Must support N >= 2 solutions.
- `entropy_mix_J_K`: positive for mixing of distinct solutions. Must be thermodynamically consistent with the reported Gibbs energies and temperature.
- `nonideality_factor`: quantifies departure of real mixing from ideal behavior. Report 1.0 when ideal mixing energy is negligible.
- `excess_volume_mL`: excess volume of mixing, in milliliters.
- `excess_gibbs_J`: excess Gibbs energy of mixing. Must be self-consistent with the other reported thermodynamic quantities.
- `min_energy_separation_kWh_m3`: minimum thermodynamic energy cost to separate the blend back into its components, per cubic meter of blend.
- `scan`: Gibbs energy of mixing as a function of volume fraction of `solutions[0]`, from 0.0 to 1.0 in `scan_steps` evenly spaced points. Total volume is the sum of the first two input solutions' volumes. Pure-component endpoints have zero mixing energy. Exactly one interior point at the global minimum is marked `"optimal": true`.
- `concentration_profile`: `gamma_mean` is the mean molal activity coefficient of the specified salt at each molality. `gamma_minimum` reports where the curve reaches its minimum. `gamma_unity_crossing_molality` is the first molality above the minimum where `gamma_mean` >= 1.0 (null if none within range).
- `dilution`: volume of pure water to add so the resulting blend's water activity reaches `target_water_activity` within +/-0.001. Report 0 if already satisfied.
- Mixing identical solutions must yield near-zero Gibbs energy and entropy.
- All output floats must be JSON-serializable (no NaN, Inf, or pint Quantity objects).
