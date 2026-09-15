Build `/app/geochem`, a Go CLI that solves aqueous geochemical equilibrium problems.

**CLI**: `/app/geochem solve <config.yaml> <output.json>`

The thermodynamic database at `/app/thermodb.json` contains Debye-Huckel parameters, basis species (charge, ion-size radius), secondary species (reaction stoichiometry, logK at 8 temperatures), and minerals. Problem configs in YAML at `/app/problems/` specify temperature, basis species constraints, charge-balance species, active secondary species, and minerals for saturation-index calculation.

**Config YAML schema** (`/app/problems/*.yaml`):
- `database`: path to database JSON
- `temperature`: degrees Celsius
- `basis`: list of `{species, constraint, value}` where constraint is one of `kg_solvent_water`, `log10_activity`, `bulk_moles`, `free_molality`
- `charge_balance_species`: species whose mass-balance equation is replaced by charge neutrality
- `active_secondary`: secondary species names to include
- `saturation_minerals`: mineral names for saturation index (not precipitated)

**Output JSON schema**: Object with fields `temperature`, `ionic_strength` (0.5 * sum z_i^2 * m_i), `water_activity`, `pH` (-log10 of H+ activity), `charge_balance_error` (sum z_i * m_i over all solutes), plus maps `basis_species` and `secondary_species` each mapping name to `{molality, activity_coefficient, activity}`, and `mineral_saturation` mapping name to `{saturation_index, log_Q, log_K}`.

The equilibrium solution must simultaneously satisfy mass-action equilibrium for every active secondary species (using logK piecewise-linearly interpolated on the database temperature grid), mass balance for each bulk-constrained component, and charge neutrality. Activity coefficients follow the extended Debye-Huckel B-dot model: `log10(gamma) = -A*z^2*sqrt(I)/(1 + B*r*sqrt(I)) + bdot*I` for charged species; neutral species have gamma=1. Water activity: `a_w = exp(-total_solute_molality / 55.51)`. All mass-balance and charge-balance residuals must converge below 1e-12.

The tool must produce correct equilibrium solutions for `/app/problems/test1.yaml` (dilute HCl), `/app/problems/test2.yaml` (NaCl-CaSO4 multi-species with gypsum SI), and `/app/problems/test3.yaml` (elevated temperature with logK interpolation).
