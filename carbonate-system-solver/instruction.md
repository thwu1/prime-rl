The carbonate chemistry solver at `/app/carbonate_solver.py` computes ocean CO2 system equilibrium from pairs of input variables (TA, DIC, pH, fCO2, CO3, HCO3) but produces results that diverge from PyCO2SYS v1.8.3 reference calculations under certain oceanographic conditions. The divergences stem from incorrect coefficients in equilibrium constant parameterizations. The nature and number of errors are not known.

Diagnose and correct the solver so that it matches PyCO2SYS (with opt_k_carbonic=10, opt_k_bisulfate=1, opt_k_fluoride=1, opt_pH_scale=1, opt_total_borate=1) within: pH +/-0.0005, fCO2/pCO2/CO3/HCO3/CO2aq relative 0.2%, OmegaCa/OmegaAr +/-0.02, Revelle +/-0.15. Round-robin consistency across all 15 input-pair combinations must hold within relative tolerance 1e-4.

An Octave script at `/app/validate_constants.m` outputs correct equilibrium constant values and pressure correction coefficients for specified temperature and salinity. Run it via `octave --no-gui --eval "T=25; S=35; run('/app/validate_constants.m')"` (add `P=3000;` for pressure-corrected values) and compare against the Python solver's constants to isolate discrepancies.

Cruise measurement data in `/app/cruise_data/` uses WOCE-exchange format: `#`-prefixed header lines, a column header row, then tab-separated records with WOCE quality flags. Use only rows where both TA_FLAG and DIC_FLAG equal 2.

Using the corrected solver, compute carbonate parameters from measured TA + DIC (with silicate and phosphate) for all acceptable cruise measurements. Perform crossover quality control per `/app/crossover_spec.json`, which pairs stations from different cruises sampling the same deep water mass.

Write results to `/app/qc_results.db` (SQLite):

- `cruise_computations`: cruise_id TEXT, station TEXT, depth REAL, temperature REAL, salinity REAL, pressure REAL, TA_measured REAL, DIC_measured REAL, pH_computed REAL, fCO2_computed REAL, pCO2_computed REAL, CO3_computed REAL, HCO3_computed REAL, OmegaCa REAL, OmegaAr REAL
- `crossover_offsets`: cruise_pair TEXT (format "cruiseA/cruiseB"), variable TEXT, mean_offset REAL (mean of cruiseA minus cruiseB values at depths exceeding the crossover minimum), n_samples INTEGER
- `adjustments`: cruise_id TEXT, variable TEXT, adjustment REAL — for each crossover the second cruise receives adjustment equal to the mean_offset

Compute offsets for variables: TA_measured, DIC_measured, pH_computed, fCO2_computed, CO3_computed, OmegaCa, OmegaAr.

The solver must not import PyCO2SYS, cbsyst, csys, mocsy, seacarb, or CO2SYS. Only numpy, scipy, and the standard library are permitted.
