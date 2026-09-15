A UNIFAC parameter database and ternary system specification are provided at `/app/`. Build a liquid-liquid equilibrium (LLE) solver that extracts parameters from the relational database, computes phase equilibria for the specified feeds, and produces both structured numerical results and a ternary phase diagram.

**Inputs**

`/app/unifac_params.sql` — SQL dump defining a normalized relational schema for original UNIFAC group-contribution parameters. Tables: `parameter_sources` (with integer `priority` ranking), `main_groups`, `subgroups` (with `rk`/`qk` van der Waals parameters), `interaction_params` (group-group `a_value` in K, referencing a `param_source_id`), `compounds`, and `compound_subgroups`. Some group-interaction pairs have rows from multiple publication sources with different `a_value` entries; the entry whose linked `parameter_sources.priority` is highest must be used. Tools `sqlite3` and `gnuplot` are available in the environment.

`/app/system.json` — Temperature (K), ordered component names (carrier, solute, solvent), and five feed mole-fraction arrays. Component names match the `compounds` table.

**Required outputs**

`/app/results.json`:
```json
{
  "system": {"components": ["..."], "temperature_K": 0},
  "tie_lines": [
    {
      "feed": [],
      "aqueous_phase": [],
      "organic_phase": [],
      "activity_coefficients_aqueous": [],
      "activity_coefficients_organic": [],
      "phase_fraction_aqueous": 0,
      "distribution_coefficients": {"name": 0},
      "selectivity_solute_over_carrier": 0
    }
  ],
  "binary_mutual_solubility": {
    "water_in_organic": 0,
    "toluene_in_aqueous": 0
  }
}
```

`/app/phase_diagram.svg` — Ternary diagram on an equilateral triangle with vertices labeled by component name. All five computed tie-lines drawn as segments connecting equilibrium phase compositions, with endpoints marked.

**Equilibrium condition**

For each component *i*: x\_i^(aq) · γ\_i^(aq) = x\_i^(org) · γ\_i^(org), where activity coefficients derive from the original UNIFAC group-contribution model.

**Success criteria**

- Isoactivity within 3 % relative tolerance per component per tie-line
- Mass balance z\_i = β · x\_i^(aq) + (1 − β) · x\_i^(org) within 0.5 % absolute
- K\_i = x\_i^(org) / x\_i^(aq) and S = K\_solute / K\_carrier internally consistent
- Binary mutual solubility: water\_in\_organic < 0.15, toluene\_in\_aqueous < 0.05
- Phase diagram: valid SVG containing triangle boundary, component labels, and five tie-line segments
