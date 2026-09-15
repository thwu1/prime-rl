Build `/app/permafrost_model.py` — a command-line tool that evaluates the permafrost thermal model specified in `/app/data/model_spec.md` using soil properties from `/app/data/thermal_params.csv`. It must support five subcommands.

**`python3 /app/permafrost_model.py forward`** — Evaluate the model for every site in `/app/data/sites.csv`. Classify each site's thermal regime per the model specification. Write `/app/output/forward_results.json`:
```json
{"sites":[{"name":"…","Tps":<float>,"ALT":<float|null>,"regime":"permafrost"|"seasonal_frost"}]}
```
`ALT` is `null` for seasonal frost sites.

**`python3 /app/permafrost_model.py calibrate`** — For each entry in `/app/data/calibration_targets.csv`, find soil fractions (`p_clay`, `p_sand`, `p_silt`, `p_peat`; each ≥ 0, sum = 1.0) that reproduce the observed active-layer thickness to within 0.01 m. Write `/app/output/calibration_results.json`:
```json
{"sites":[{"name":"…","p_clay":<f>,"p_sand":<f>,"p_silt":<f>,"p_peat":<f>,"predicted_ALT":<f>,"observed_ALT":<f>,"residual":<f>}]}
```

**`python3 /app/permafrost_model.py sensitivity`** — For each permafrost site, find the minimum positive increase in mean annual air temperature (±0.01 °C) that would cause the site to lose its permafrost regime. Write `/app/output/sensitivity_results.json`:
```json
{"sites":[{"name":"…","delta_Ta_critical":<float>,"current_Tps":<float>}]}
```

**`python3 /app/permafrost_model.py project`** — Read borehole observations from `/app/data/borehole_obs.tsv` and site mappings from `/app/data/site_borehole_map.csv`. For boreholes with ≥ 5 non-missing temperature values, derive the decadal warming trend. Estimate years until permafrost loss for permafrost sites exhibiting warming. Write `/app/output/projection_results.json`:
```json
{"sites":[{"name":"…","borehole_id":"…","warming_trend_decade":<f|null>,"delta_Ta_critical":<f|null>,"years_to_loss":<f|null>}]}
```
`warming_trend_decade` and `years_to_loss` are null when fewer than 5 measurements exist. `delta_Ta_critical` and `years_to_loss` are null for seasonal frost sites.

**`python3 /app/permafrost_model.py uncertainty`** — Read parameter uncertainties from `/app/data/param_uncertainties.csv` (columns: `param`, `abs_std`). For each permafrost site, propagate input uncertainties through the model to TTOP and ALT following the numerical conventions in the model spec appendix. Identify the parameter whose uncertainty contributes most to TTOP uncertainty. `vulnerability_index` expresses how large the TTOP uncertainty is relative to the warming margin from `sensitivity`. Write `/app/output/uncertainty_results.json`:
```json
{"sites":[{"name":"…","sigma_TTOP":<f>,"sigma_ALT":<f|null>,"dominant_param":"…","vulnerability_index":<f>,"jacobian_TTOP":{"Ta":<f>,…},"jacobian_ALT":{"Ta":<f>,…}}]}
```

**Constraints**: Create `/app/output/` if absent. Automatically run prerequisite subcommands when their outputs are missing. Handle domain boundaries and regime transitions during perturbations.
