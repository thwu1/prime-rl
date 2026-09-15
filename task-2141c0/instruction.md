`/app/data/` contains CFD verification data from NASA's Turbulence Modeling Resource — flat plate simulations at Re=5×10⁶ using the Spalart-Allmaras turbulence model, computed independently by CFL3D and FUN3D. Data files use PLOT2D structured grid format and Tecplot ASCII multi-zone format.

Produce three deliverables:

**`/app/results.json`** conforming to this exact schema:

```json
{
  "grid": {"nx": ..., "ny": ..., "y1": ..., "max_stretch_ratio": ...},
  "convergence": {
    "cfl3d_cf": {"p": ..., "f_ext": ..., "e_a_pct": ..., "gci_pct": ..., "monotonic": ...},
    "fun3d_cf": {...}, "cfl3d_cd": {...}, "fun3d_cd": {...}
  },
  "boundary_layer": {"delta99": ..., "delta_star": ..., "theta": ..., "H": ...},
  "log_law": {"kappa_fit": ..., "B_fit": ..., "rms_standard": ...},
  "eddy_viscosity": {"peak_mut": ..., "peak_y": ..., "monotonic_to_peak": ...}
}
```

The `convergence` section covers skin friction and drag from both codes. Boundary layer and log-law quantities use the profile at x=0.97008. Eddy viscosity analysis uses CFL3D data near x≈0.97.

**`/app/plots/convergence.eps`** — an EPS-format grid convergence plot generated with **gnuplot** showing skin friction coefficient vs. grid spacing for both CFL3D and FUN3D, with extrapolated grid-independent values indicated. Use log scale on the grid spacing axis.

**`/app/benchmark.db`** — a **SQLite** database containing:
- `convergence_raw` (code TEXT, quantity TEXT, grid_n REAL, grid_h REAL, value REAL) — raw grid study data
- `convergence_results` (code TEXT, quantity TEXT, p REAL, f_ext REAL, e_a_pct REAL, gci_pct REAL, monotonic INTEGER)
- `boundary_layer_profile` (u REAL, y REAL) — velocity profile at x=0.97008
- `analysis_summary` (result_name TEXT, result_value REAL) — all scalar results from the analysis