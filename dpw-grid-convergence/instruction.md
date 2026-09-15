Six participant CFD submissions from the DPW-8 (8th AIAA Drag Prediction Workshop) are at `/app/submissions/` in the standard DPW Tecplot ASCII format. Experimental wind tunnel reference data is at `/app/experimental/crm_wb_etw.dat`. Format documentation is at `/app/format_spec.txt`.

Produce a numerical verification and validation assessment of the CRMWB (Wing/Body) configuration at α = 2.50°. The assessment must estimate grid-independent aerodynamic coefficients with quantified numerical uncertainty for each participant, identify submissions exhibiting unreliable grid convergence behavior, and compute ensemble statistics across credible participants referenced against experimental data.

Deliver these artifacts:

**`/app/results/convergence.db`** — SQLite database with tables:
- `raw_data` (participant_id TEXT, grid_level INTEGER, grid_size INTEGER, cl REAL, cd REAL, cm REAL, solver TEXT, turbulence_model TEXT) — parsed CRMWB grid convergence data for all participants
- `convergence_assessment` (participant_id TEXT, coefficient TEXT, convergence_order REAL, asymptotic_value REAL, numerical_uncertainty REAL, is_valid INTEGER) — per-participant, per-coefficient convergence analysis results

**`/app/results/grid_convergence.json`**:
```json
{
  "participants": {
    "<id>": {
      "solver": "<name>",
      "turbulence_model": "<model>",
      "CL": {"convergence_order": "<float|null>", "asymptotic_value": "<float|null>", "numerical_uncertainty": "<float|null>"},
      "CD": {},
      "CM": {}
    }
  },
  "refinement_ratio": "<float>",
  "grid_sizes": ["<int>"]
}
```
Set fields to `null` for participants with unreliable convergence.

**`/app/results/anomalies.json`**:
```json
{
  "flagged": {
    "<id>": {"reasons": ["..."], "coefficients_affected": ["CL"]}
  }
}
```

**`/app/results/ensemble.json`**:
```json
{
  "valid_participants": ["<id>"],
  "statistics": {
    "CL": {"mean": "<float>", "std": "<float>"},
    "CD": {},
    "CM": {}
  },
  "experimental_reference": {"CL": "<float>", "CD": "<float>", "CM": "<float>"}
}
```

**`/app/results/plots/`** — Grid convergence plots generated with `gnuplot`: `cl_convergence.png`, `cd_convergence.png`, `cm_convergence.png`. Each plot must show coefficient versus mesh spacing parameter for all participants, with asymptotic estimates indicated.

Only CRMWB configuration data should be included in the analysis. The submission files contain multiple zone types and configurations that must be correctly identified and filtered.