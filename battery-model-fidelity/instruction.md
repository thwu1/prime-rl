A PyBaMM simulation script at `/app/cell_analysis.py` performs a comparative fidelity study of lithium-ion battery models (SPM and DFN) for an LG M50 cell using the Chen2020 parameter set. The script discharges the cell at multiple C-rates, compares model predictions, and examines thermal and electrolyte transport behavior.

The script runs without crashing (`python3 /app/cell_analysis.py`) and produces `/app/results.json`. However, the results contain multiple physically inconsistent values that contradict the known behavior of this cell. Expected cell characteristics are documented in `/app/cell_specs.json`.

Diagnose all issues in the script, correct them, and regenerate `/app/results.json` with physically valid simulation results consistent with standard Chen2020 model behavior.