Build a pharmacokinetic analysis pipeline at `/app/` that processes DrugBank XML drug monographs and clinical dosing scenarios to produce steady-state pharmacokinetic assessments and a cross-referencing validation report.

**Inputs** (pre-installed):
- `/app/drugbank_excerpt.xml` — Namespaced DrugBank XML containing 20 drug entries with free-text `<half-life>` elements and structured `<pharmacokinetic-parameters>` (volume of distribution, protein binding, therapeutic range)
- `/app/dosing_scenarios.json` — 15 clinical dosing scenarios referencing drugs by DrugBank ID
- `/app/curated_reference.tsv` — Tab-separated file with independently curated numeric half-life values (hours) for a subset of the drugs

**Deliverables:**

`python3 /app/pk_engine.py` must write `/app/output/results.json`:
```json
{
  "drug_extractions": [
    {"drugbank_id": "...", "parsed_half_life_hours": 0.0, "elimination_rate_constant_per_h": 0.0}
  ],
  "scenario_analyses": [
    {
      "scenario_id": "...", "drugbank_id": "...",
      "parsed_half_life_hours": 0.0, "ke_per_h": 0.0,
      "vd_L": 0.0, "clearance_L_per_h": 0.0,
      "accumulation_factor": 0.0,
      "cmax_steady_state_mg_L": 0.0, "cmin_steady_state_mg_L": 0.0,
      "auc_steady_state_mg_h_per_L": 0.0,
      "time_to_90pct_steady_state_h": 0.0,
      "therapeutic_status": "...",
      "recommended_interval_h": null
    }
  ]
}
```

`bash /app/validate.sh` must write `/app/output/reconciliation.tsv` — tab-separated with header row and columns: `drugbank_id`, `parsed_hours`, `curated_hours`, `pct_discrepancy`, `status`. Include only drugs present in both the XML extractions and the curated reference. Status is `MATCH` when absolute percent discrepancy is at most 5%, otherwise `MISMATCH`.

**Constraints:**
- Half-life values in the XML are free-text strings with varied formats, units, qualifiers, and clinical context that must be interpreted as numeric hours
- Model: one-compartment, instantaneous absorption; for non-IV routes apply the scenario's bioavailability factor to the effective dose
- Therapeutic status: `in_range`, `below_min`, `above_max`, `both_violated` — classified by comparing steady-state trough against minimum and peak against maximum effective concentrations
- `recommended_interval_h`: longest integer dosing interval in [1, 720] hours keeping steady-state peak and trough within the therapeutic window at the given dose; `null` if no valid interval exists; `null` for `in_range` scenarios
- Numeric precision: at least 4 significant figures
- Tools available in the environment: `python3`, `jq`, `xmlstarlet`
