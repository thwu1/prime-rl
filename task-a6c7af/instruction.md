Build `/app/pipeline.sh` — a shell pipeline that reads NIST WebBook reference data from `/app/data/`, loads parsed data into a SQLite database, computes Peng-Robinson EOS predictions for CO2, and produces validated JSON output. The pipeline must orchestrate multiple tools: Python for computation, `sqlite3` CLI for database queries, and `jq` for JSON extraction.

Data sources: isothermal PVT in `/app/data/co2_{250,300,350,400}K.tsv` (tab-separated, undocumented column layout), multi-source critical property measurements in `/app/data/critical_measurements.csv` (contains multiple fluids — extract CO2 and reconcile conflicting values), and NIST saturation reference data in `/app/data/co2_saturation_nist.html`.

The pipeline must produce three artifacts:

**`/app/thermo.db`** — SQLite database with tables:
- `nist_isotherms` (`temperature_K REAL, pressure_bar REAL, volume_L_mol REAL, phase TEXT`) — all parsed rows from the four isotherm files
- `critical_props` (`fluid TEXT, property TEXT, value REAL, uncertainty REAL, source TEXT`) — all rows from the CSV
- `saturation_ref` (`temperature_K REAL, pressure_bar REAL`) — parsed from the HTML saturation table

**`/app/results.json`** — eight top-level keys:

`critical_params` — `{"Tc_K", "Pc_bar", "omega"}` — consensus CO2 parameters derived from the multi-source measurements.

`compressibility` — Keyed by temperature string ("250"–"400"). Each: array of `{"P_bar", "Z_PR", "Z_NIST", "phase"}`, one entry per unique pressure. Duplicate pressures in the source data must be collapsed.

`fugacity` — `[{"T_K", "P_bar", "ln_phi"}]` at (300,10), (300,50), (350,100), (400,200).

`departure_enthalpy` — `[{"T_K", "P_bar", "H_dep_kJ_per_mol"}]` at the same four state points.

`second_virial` — `[{"T_K", "B_data_cm3_per_mol", "B_PR_cm3_per_mol"}]` at T=250, 300, 350, 400 K. Units: cm³/mol.

`vle_prediction` — `[{"T_K", "P_sat_bar"}]` for T=280 and 290 K.

`compression_work` — `{"T_K": 350, "P1_bar": 1, "P2_bar": 80, "W_ideal_kJ_per_mol", "W_real_kJ_per_mol"}`. Minimum isothermal compression work in kJ/mol.

`model_accuracy` — `saturation_validation`: `[{"T_K", "P_sat_nist_bar", "P_sat_predicted_bar", "relative_error"}]` for 280 and 290 K cross-validated against the HTML data. `compressibility_rmse`: keyed by temperature, each `{"rmse", "max_abs_error", "n_points"}`.

**`/app/validation.json`** — Cross-check report generated within the pipeline using `jq` to query `results.json` and `sqlite3` CLI to query `thermo.db`. Schema: `{"keys_present": [<sorted top-level key names>], "n_isotherms": <total compressibility entries summed across all temperatures>, "n_fugacity": <count>, "n_virial": <count>, "db_isotherm_count": <nist_isotherms row count>, "db_saturation_count": <saturation_ref row count>}`.

Execute: `bash /app/pipeline.sh`
