Build a compressible flow tool at `/app/inlet_solver.py` that reads `/app/inlet_config.json` and writes results to `/app/results.json`.

The analyzer must support calorically perfect gas (CPG, constant γ) and thermally perfect gas (TPG, polynomial Cp(T) = c0 + c1·T + c2·T² + c3·T³ with p = ρRT, R = 287.05 J/(kg·K)).

Implement these case types as specified in the config:

- `single_oblique`: Solve the θ-β-M relation for the weak shock. Return `beta_deg`, `M2`, `p2_p1`, `T2_T1`, `rho2_rho1`, `p02_p01`.
- `normal_shock`: Normal shock properties. Same output fields as above.
- `max_deflection`: Maximum deflection angle before shock detachment. Return `theta_max_deg`.
- `multi_ramp`: Chain sequential oblique shocks (each shock's downstream conditions become the next shock's upstream). Return a `shocks` array where each entry has `M1`, `beta_deg`, `M2`, `p2_p1`, `T2_T1`, `rho2_rho1`, `p02_p01`, plus `total_p0_recovery` (product of individual p0 ratios).
- `optimize_equal_ramps`: Find the equal-deflection ramp angle for N ramps followed by a terminal normal shock that maximizes overall total pressure recovery. Return `optimal_theta_deg`, `total_p0_recovery` (including terminal normal shock), and `final_M` (Mach after oblique shocks, before the terminal normal shock).
- `single_oblique_tpg`: Oblique shock with TPG model — iteratively solve conservation equations with temperature-dependent specific heat. Return `beta_deg`, `M2`, `T2_K`, `p2_Pa`, `rho2_rho1`, `p02_p01`.

Output format: `{"cases": [{"id": "<case_id>", ...}, ...]}` with each case's `id` matching the input config.