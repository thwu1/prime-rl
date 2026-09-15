Build a Python command-line tool at `/app/geochem_pipeline.py` that performs geochemical water quality analysis using PHREEQC. It reads `/app/waters.json` (containing four water analyses and analysis configuration) and writes `/app/results.json`. Run as `python3 /app/geochem_pipeline.py` with no arguments.

`/app/results.json` must be a JSON object with these top-level keys:

**`charge_balance`**: Object keyed by water ID. Each entry: `cbe_pct` (float, charge balance error percentage; positive means excess cations), `adjusted` (bool, true if |CBE| exceeded the configured `charge_balance_threshold_pct`). Waters flagged as adjusted must use charge-balanced compositions in all subsequent analyses.

**`speciation`**: Object keyed by water ID. Each entry: `pH` (float), `pe` (float), `ionic_strength` (float, mol/kgw), `SI_Calcite` (float), `SI_Dolomite` (float), `SI_Gypsum` (float), `SI_Fluorite` (float or null if F absent in the water analysis), `SI_SiO2_a` (float or null if Si absent).

**`ccpp`**: Calcium Carbonate Precipitation Potential for the water specified in `ccpp_analysis`. Fields: `water_id` (string), `CCPP_closed_mmol_kgw` (float, positive means net precipitation), `CCPP_open_mmol_kgw` (float), `final_pH_closed` (float), `final_pH_open` (float). The configuration supplies the target CO2 log partial pressure for the open-system case.

**`blend_analysis`**: Binary mixing of the two configured source waters at the ratios in `blend_analysis.ratios_a`. Fields: `ratio_a` (list[float]), `SI_Calcite` (list[float]), `pH` (list[float]), `ionic_strength` (list[float]), `optimal_ratio_min_abs_SI_Calcite` (float -- the ratio from the list that minimizes |SI_Calcite|).

**`evaporation`**: Evaporative concentration of the designated water at the concentration factors in `evaporation.concentration_factors`, maintaining mineral equilibria for the phases listed in `evaporation.equilibrium_phases`. Fields: `concentration_factors` (list[int]), `pH` (list[float]), `ionic_strength` (list[float]), `minerals_precipitated` (object: mineral name to list[float] of cumulative moles precipitated per kg original water at each step), `first_precip_factor` (object: mineral name to int or null -- lowest concentration factor at which that mineral first precipitates).

All computations must use the `phreeqc.dat` thermodynamic database. Alkalinity formats in the input follow PHREEQC conventions.
