Air species thermodynamic data in NASA 7-coefficient polynomial format is at `/app/data/species.json`, and flight conditions are at `/app/data/conditions.json`.

Implement a compressible flow solver that computes oblique shock wave properties for a **thermally perfect gas** (TPG). In the TPG model, specific heat Cp varies with temperature per the NASA polynomial fits, unlike the calorically perfect gas (CPG) approximation where the ratio of specific heats gamma is fixed at 1.4. The TPG model is essential for hypersonic flows where post-shock temperatures cause vibrational excitation of air molecules, changing the effective gamma.

For each condition (upstream Mach number M1, stagnation temperature Tt, flow deflection angle theta), compute freestream static temperature and effective gamma, normal shock properties (M2, P2/P1, T2/T1, rho2/rho1, Pt2/Pt1), weak and strong oblique shock solutions (shock angle beta and all downstream property ratios), and the maximum deflection angle (detachment condition). Write results to `/app/results/flow_tables.json`.

Output JSON structure per condition (keyed by condition id):
```json
{
  "freestream": {"T_static_K": ..., "gamma_effective": ...},
  "normal_shock": {"M2": ..., "P2_P1": ..., "T2_T1": ..., "rho2_rho1": ..., "Pt2_Pt1": ...},
  "weak_shock": {"beta_deg": ..., "M2": ..., "P2_P1": ..., "T2_T1": ..., "rho2_rho1": ..., "Pt2_Pt1": ...},
  "strong_shock": {"beta_deg": ..., "M2": ..., "P2_P1": ..., "T2_T1": ..., "rho2_rho1": ..., "Pt2_Pt1": ...},
  "detachment_angle_deg": ...
}
```

The shock jump conditions (Rankine-Hugoniot) must be solved iteratively since the caloric equation of state is nonlinear. At low temperatures where Cp is approximately constant, results should converge to standard CPG values (gamma = 1.4 for air).