Calibrate constitutive models for DP800HHE dual-phase steel and evaluate a multi-team forming benchmark. Work in `/app/`, read from `/app/data/`, write all outputs to `/app/output/`.

**Inputs** (`/app/data/`): `tensile_tests.json` (true stress vs. plastic strain at 0°, 45°, 90° to rolling direction), `bulge_test.json` (equivalent stress vs. equivalent strain), `material_params.json` (Lankford R-values at 0°, 22.5°, 45°, 67.5°, 90°; stress ratios; Young's modulus), `ground_truth.json` and `submissions.json` (force and strain field data for specimen widths `"70"`, `"110"`, `"230"` from 5 teams).

**Required outputs** (all `/app/output/`):

`fitted_parameters.json` — Swift, Voce, and Hockett-Sherby hardening models calibrated against 0° tensile + bulge data. Schema: `{"swift":{"K","eps_0","n"}, "voce":{"sigma_sat","sigma_y","theta"}, "hockett_sherby":{"sigma_sat","sigma_i","m","n"}}`. All positive. Fit RMSE: HS < 3 MPa, Voce < 20 MPa, Swift < 40 MPa.

`flow_curves.json` — Each model evaluated at strains `[0.001, 0.005, 0.01, 0.02, 0.05, 0.10, 0.20, 0.30, 0.40, 0.50]`. Schema: `{"strains":[…],"swift":[…],"voce":[…],"hockett_sherby":[…]}`. Within 0.1 MPa of fitted parameters; monotonically increasing.

`blended_model.json` — Optimal convex combination of the three hardening models minimizing RMSE against calibration data. Schema: `{"weights":{"swift","voce","hockett_sherby"}, "rmse":<float>, "stresses_at_eval_strains":[…]}`. Weights non-negative, sum to 1.0. RMSE must not exceed the best individual model's RMSE. Evaluate blended stresses at the same 10 strains as `flow_curves.json`.

`hill48_parameters.json` — Hill48 anisotropic yield criterion calibrated from R-values under associated flow rule (plane stress). Schema: `{"F","G","H","N"}`. All positive, G+H > 0. R-value constraints satisfied within 1e-4.

`yield_locus.csv` — 360 rows (0°–359°, 1° increments), columns: `angle,sigma_1,sigma_2`. Normalized principal stress space. All points on the Hill48 surface within 1e-4. σ₂ ≈ 0 at 0°; σ₁ ≈ σ₂ at 45°.

`directional_properties.json` — Predictions at `[0.0, 22.5, 45.0, 67.5, 90.0]` degrees. Schema: `{"angles":[…],"normalized_yield_stress":[…],"predicted_r_values":[…],"r_value_errors":[…]}`. Yield stress = 1.0 at 0°, range [0.9, 1.15]. R-values match measurements within 1e-4 at 0°, 45°, 90°; range [0.5, 2.0]. Errors = |predicted − measured|.

`anisotropic_flow_curves.json` — Predict uniaxial stress-strain at 45° and 90° by coupling the best-fitting hardening model with Hill48 directional yield stress ratios and the corresponding axial-to-equivalent strain mapping. Schema: `{"best_model":"<name>","yield_stress_ratios":{"45","90"},"predicted_45":[…],"predicted_90":[…],"measured_45_stress":[…],"measured_45_strain":[…],"measured_90_stress":[…],"measured_90_strain":[…],"rmse_45":<float>,"rmse_90":<float>}`. Predictions at measured strain points. RMSE < 50 MPa per orientation.

`benchmark_scores.json` — Normalized RMSE scoring across 5 teams and 3 specimen configs. Per team per config: RMSE for force, major strain (mean of xz/yz section RMSEs), minor strain (mean of xz/yz section RMSEs). Normalization factor per config-metric pair: mean RMSE across all teams. Per-metric score: mean normalized RMSE across configs. Total: sum of 3 metric scores. Schema: `{"normalization_factors":{config:{"force","major_strain","minor_strain"}},"team_scores":{team:total},"ranking":[best_to_worst]}`. Ascending by total; team_A first, team_E last; within 1e-3.
