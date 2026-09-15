Build a membrane gas separation analysis system at `/app/`.

**Input data** is at `/app/data/`: `gas_properties.json` (critical properties, acentric factors, binary interaction parameters for CO2, CH4, N2, O2, H2, He), `robeson_parameters.json` (2008 upper-bound k and n for 10 gas pairs), `polymer_database.json` (permeabilities for 12 polymers), `cascade_scenario.json` (two-stage cascade specification), and `nist/<GAS>_<P>atm.tsv` (NIST isobaric reference tables with density, phase, and other thermodynamic columns).

**Python CLI** -- `/app/membrane_analysis/` package, invoked as `python3 -m membrane_analysis <subcommand>`, JSON to stdout.

`eos --gas <NAME> --T <K> --P <bar>` -- Pure-component output: `{"gas","T_K","P_bar","Z","phi","fugacity_bar"}`. Mixture mode: `--gas A,B --composition xA,xB` produces `{"gases","composition","T_K","P_bar","Z_mix","phi":{per component},"fugacity_bar":{per component}}`.

`validate --gas <NAME> --pressure <atm>` -- JSON array of `{"T_K","P_bar","Z_computed","Z_nist","relative_error"}`, ascending by temperature. `Z_nist` derived from NIST reference data. Accuracy: relative error <2% at 1 atm for T > 1.5 Tc; <3% at 50 atm for T > 1.5 Tc (T > 6 Tc for H2).

`robeson --gas-pair A/B [--polymer ABBREV]` -- JSON array of `{"polymer","P_A","alpha","P_upper_bound","ratio","exceeds_bound"}`. `ratio` = P_A / P_upper_bound at the polymer's selectivity. Without `--polymer`: all polymers sorted descending by ratio.

`cascade --config <path>` -- Two-stage membrane cascade with recycle per the scenario configuration. Output: per-stage `area_m2`, `stage_cut`, `retentate`/`permeate` composition dicts keyed by gas name; `product`/`reject` with `flow_mol_per_s` and `CO2_mol_frac`; `recycle` with `flow_mol_per_s` and `CO2_mol_frac`; `methane_recovery`; `converged` (bool); `iterations`. Overall molar balance (feed = product + reject) within 0.1%.

**Makefile** at `/app/Makefile`:

`make preprocess` -- For each NIST TSV, produce `/app/processed/<GAS>_<P>atm.csv` with header `gas,temperature_k,pressure_atm,density_kg_m3,z_nist`. Vapor-phase rows only.

`make database` -- Create `/app/analysis.db`. Tables: `nist_reference(gas TEXT, temperature_k REAL, pressure_atm REAL, density_kg_m3 REAL, z_nist REAL)`, `eos_validation(gas TEXT, temperature_k REAL, pressure_bar REAL, z_computed REAL, z_nist REAL, relative_error REAL)`, `robeson_ranking(gas_pair TEXT, polymer TEXT, p_a REAL, alpha REAL, p_upper_bound REAL, ratio REAL, exceeds_bound INTEGER)`. View `worst_eos_errors`: gas, temperature_k, relative_error from eos_validation, descending by relative_error, limit 10. Populate all tables from preprocessed data and CLI output.

`make report` -- Produce `/app/report.json`: `{"total_nist_points","mean_relative_error","max_relative_error","polymers_exceeding_bound":[...],"gas_pairs_evaluated"}`.

`make all` -- Full pipeline.
