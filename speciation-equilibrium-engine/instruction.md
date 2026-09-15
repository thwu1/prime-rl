Build an aqueous geochemical speciation engine that computes equilibrium distributions of dissolved species and mineral saturation indices from thermodynamic databases.

Input files at `/app/`:

- `/app/species.dat` — aqueous complexation reaction database with `COMPONENTS` and `SPECIES` sections. Each species line defines a formation reaction with a `log_k` value. The derived species name appears on the right side of `=`. Stoichiometric coefficients precede species names (default 1). H2O has activity 1. Includes multi-nuclear complexes where multiple metal ions combine (e.g. `2 Fe+3 + 2 H2O = Fe2(OH)2+4 + 2 H+`).

- `/app/phases.dat` — mineral dissolution reaction database with a `PHASES` section. Each line: `mineral_name | dissolution_reaction | log_k = value`. The solid mineral formula appears on the left of `=`; aqueous products on the right. H+ may appear on either side.

- `/app/scenarios.json` — array of scenarios, each with `name`, `pH`, and `total_concentrations` (component name to total molar concentration). Only components listed in a scenario's `total_concentrations` (plus H+) participate in that scenario's equilibrium.

Write results to `/app/results.json` with this schema:

```json
{
  "scenarios": [
    {
      "name": "<string>",
      "free_concentrations": {"<component>": <float>, ...},
      "species_concentrations": {"<species_name>": <float>, ...},
      "saturation_indices": {"<mineral_name>": <float>, ...}
    }
  ]
}
```

- `free_concentrations`: uncomplexed concentration of H+ and each scenario component (mol/L).
- `species_concentrations`: every derived aqueous species with concentration >= 1e-20 M.
- `saturation_indices`: SI = log10(IAP / K) for every mineral whose required components are all present in the scenario. IAP uses the same stoichiometric exponents as the dissolution reaction (positive for products, negative for non-mineral reactants like H+).

Constraints: ideal dilute solutions (all activity coefficients = 1, water activity = 1). pH is fixed — do not enforce proton mass balance. Enforce mass balance for every non-H+ component: total = free + sum of (stoichiometric coefficient × species concentration) over all relevant species. All data at 25°C.
