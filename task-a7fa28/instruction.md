Two compressible RANS solvers (CFL3D and FUN3D) each computed a zero-pressure-gradient turbulent flat plate flow (M=0.2, Re_L=5×10⁶) with the Spalart-Allmaras model on five nested structured grids (uniform refinement ratio r=2). Grid convergence data, finest-grid flow profiles, and the coarsest-level grid are provided in `/app/data/`.

Evaluate the numerical reliability and accuracy of both solvers. Determine which solver/metric combinations yield trustworthy grid-converged results and which do not. Produce a verification report as `/app/results.json` conforming to the schema below.

## Data (`/app/data/`)

| File | Contents |
|------|----------|
| `cf_convergence.dat` | Cf at x≈0.97 across grid levels, Tecplot multi-zone (columns: N, h², h, Cf) |
| `drag_convergence.dat` | Total drag coefficient, same format |
| `flatplate_u.dat` | Velocity profiles (u, y) at streamwise stations, CFL3D finest grid |
| `mut_profile.dat` | Eddy viscosity ratio μ_t/μ_∞ profile at x≈0.97 (columns: x, y, μ_t/μ_∞) |
| `flatplate_grid.p2d` | PLOT3D 2D ASCII single-block structured grid, coarsest level |

## Output (`/app/results.json`)

`<metric>` ∈ {`skin_friction`, `drag`}; `<code>` ∈ {`CFL3D`, `FUN3D`}.

```json
{
  "gci": {
    "<metric>": { "<code>": {
      "p": 0, "ea21_pct": 0, "eext21_pct": 0,
      "gci_fine_pct": 0, "f_extrapolated": 0
    }}
  },
  "convergence_assessment": {
    "<metric>": { "<code>": {
      "monotonic": false, "in_asymptotic_range": false
    }}
  },
  "grid_quality": {
    "dimensions": [0, 0],
    "min_wall_spacing": 0,
    "max_stretching_ratio": 0,
    "plate_points": 0
  },
  "boundary_layer": {
    "delta_99": 0, "delta_star": 0,
    "theta": 0, "shape_factor": 0
  },
  "sa_verification": {
    "peak_chi": 0, "peak_y": 0,
    "freestream_chi": 0, "peak_mut_over_mu": 0
  }
}
```

All values as JSON numbers; `monotonic` and `in_asymptotic_range` are booleans. Standard CFD V&V definitions and SA model definitions apply throughout. Grid quality covers the flat plate surface (0 ≤ x ≤ 2). Boundary layer integral properties use the profile at x ≈ 0.97. The SA working variable χ must be recovered from the eddy viscosity data.