A QSAR virtual screening prototype at `/app/prototype.py` processes training molecules (`/app/training_data.csv`, SMILES with pIC50 activity values) and candidate compounds (`/app/screening_library.csv`) to identify drug-like lead compounds. The pipeline builds a predictive model, applies multi-stage filtering, assesses applicability domain, and selects diverse representatives.

The prototype executes without runtime errors but contains multiple scientific methodology mistakes that produce invalid results — selected leads fail independent validation against established medicinal chemistry standards.

Diagnose all domain-specific errors in the prototype and produce a corrected pipeline that writes a valid `/app/report.json` with the following structure:

- `model_performance`: `r_squared` (float), `rmse` (float), `n_train` (int), `n_test` (int)
- `pipeline_summary`: `n_screening`, `n_valid`, `n_active`, `n_after_lipinski`, `n_after_veber`, `n_after_pains`, `n_after_brenk`, `n_in_ad`, `n_clusters`, `n_selected` (all int)
- `selected_leads`: list of objects with `smiles` (str), `predicted_pIC50` (float), `MW` (float), `LogP` (float), `TPSA` (float), `QED` (float), `cluster_id` (int)

Precision: pIC50/LogP/QED to 4 decimal places; MW/TPSA/r_squared/rmse to 2 decimal places.