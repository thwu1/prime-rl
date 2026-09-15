Five research groups submitted CFD solver results for the ONERA OAT15A transonic airfoil (M=0.73, Re=3×10⁶) to a drag prediction workshop. Each group used a different flow solver and submitted their data in a different file format.

Data is in `/app/data/`:
- `experiment.csv` — Wind tunnel force/moment reference measurements
- `grid_spec.csv` — Grid refinement level cell counts
- `submission_fun3d_sa.dat`, `submission_overflow_sst.csv`, `submission_su2_sa.fwf`, `submission_tau_rsm.jsonl`, `submission_cfl3d_sa.tsv` — Solver submissions (five files, each a different format)

Each submission contains force coefficients (CL, CD, CM) at multiple grid refinement levels for a fixed angle of attack, plus a full angle-of-attack sweep at the finest grid. The grid family uses a uniform refinement ratio of 2 in each direction.

Evaluate each solver's grid convergence quality, prediction accuracy relative to the wind tunnel data, and identify any anomalous results. Produce a ranked assessment of overall solver quality.

Write `/app/evaluation.json`:
```json
{
  "solvers": {
    "<SOLVER_NAME>": {
      "convergence_order": <observed spatial convergence rate>,
      "converged_cl": <grid-independent CL estimate>,
      "converged_cd": <grid-independent CD estimate>,
      "cl_rms_error": <RMS CL error vs experiment across alpha sweep>,
      "cd_rms_error": <RMS CD error vs experiment across alpha sweep>,
      "anomaly": <true if anomalous convergence behavior detected>
    }
  },
  "ranking": ["<best_solver>", "...", "<worst_solver>"],
  "best_solver": "<name>",
  "worst_solver": "<name>"
}
```

Generate comparison plots as PNG files in `/app/plots/` using gnuplot. Save the gnuplot scripts as `.gp` files alongside the plots. At minimum produce a grid convergence comparison plot and a drag polar comparison plot against the experimental data.