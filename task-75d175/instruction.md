An OpenFOAM steady-state incompressible flow case at `/app/cavity/` is supposed to simulate the classic lid-driven cavity at Reynolds number 100 using `simpleFoam`, but the case contains multiple configuration errors across mesh definition, numerical schemes, solver settings, and physical parameters that prevent successful execution or convergence.

**Part 1 — Fix the case** so that `blockMesh` produces a valid mesh and `simpleFoam` converges (all final residuals below 1e-4).

**Part 2 — Create a mesh convergence validation script** at `/app/analyze.py` that evaluates the numerical accuracy of the corrected simulation by performing a Richardson extrapolation-based mesh convergence study:

- Run the corrected case at three mesh refinement levels (20x20, 40x40, 80x80; uniform refinement ratio r=2) by programmatically modifying `blockMeshDict`, cleaning, and re-running `blockMesh` + `simpleFoam` for each level. Use very tight solver convergence settings (e.g. residualControl 1e-8 or tighter, solver tolerance 1e-10, relTol 0) so that iterative error is negligible compared to discretization error.
- For each mesh level, extract the u-velocity profile along the vertical centerline (x = L/2) by interpolating between the two cell columns bracketing the centerline.
- At the five normalized y-coordinates below (from the Ghia et al. 1982 Re=100 benchmark), compute Richardson extrapolation estimates of the grid-converged velocity, the observed order of convergence p, and the Grid Convergence Index (GCI with safety factor Fs=1.25, using relative error form: epsilon = (u_fine - u_medium) / u_fine):

| y_normalized | u_ghia   |
|-------------|----------|
| 0.9766      | 0.84123  |
| 0.5000      | -0.20581 |
| 0.2813      | -0.15662 |
| 0.1016      | -0.06434 |
| 0.0547      | -0.03717 |

- Determine whether the fine mesh is in the asymptotic range of convergence.
- Write all results to `/app/convergence_report.json` with this structure:

```json
{
  "mesh_levels": [20, 40, 80],
  "refinement_ratio": 2.0,
  "sample_points": [
    {
      "y_normalized": 0.9766,
      "u_coarse": ...,
      "u_medium": ...,
      "u_fine": ...,
      "u_extrapolated": ...,
      "u_ghia": 0.84123,
      "observed_order": ...,
      "gci_fine": ...
    }
  ],
  "asymptotic_range": true
}
```

The OpenFOAM environment is available via `source /usr/lib/openfoam/openfoam2312/etc/bashrc`. The case uses the standard OpenFOAM directory layout (`0/`, `constant/`, `system/`).