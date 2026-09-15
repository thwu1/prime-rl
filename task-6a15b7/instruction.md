OpenFOAM simulation results for single-phase flow through a 2D packed-bed porous medium are stored in `/data/cases/`. The dataset includes a mesh resolution study and a pressure-drop sweep spanning linear through inertia-dominated flow regimes. Physical and geometric parameters are embedded within the case directories following standard OpenFOAM conventions.

Perform a rigorous numerical verification and physical validation assessment. Produce the following outputs in `/app/`:

### 1. `results.json`

```json
{
  "verification": {
    "permeabilities": [k_coarse, k_medium, k_fine],
    "convergence_order": <float>,
    "asymptotic_ratio": <float>,
    "extrapolated_value": <float>,
    "discretization_uncertainty_pct": <float>,
    "in_asymptotic_range": <bool>
  },
  "validation": {
    "intrinsic_permeability": <float>,
    "inertial_coefficient": <float>,
    "transition_reynolds": <float>,
    "kozeny_carman_permeability": <float>,
    "validation_error_pct": <float>
  }
}
```

**verification**: Quantify numerical discretization error from the three mesh resolutions. Report per-mesh Darcy permeabilities (ordered coarse-to-fine), the observed spatial convergence rate, a grid-independent permeability estimate, and the discretization uncertainty as a percentage. The asymptotic ratio assesses whether successive grid refinements converge at a consistent rate (should approach unity; classify as achieved if within 5%).

**validation**: Characterize the nonlinear pressure-velocity relationship across the pressure-drop sweep to extract the linear (viscous) and nonlinear (inertial) transport coefficients (the latter in units of m⁻¹). Determine the pore Reynolds number (based on particle diameter) at which inertial effects contribute 10% of the total pressure gradient. Compare the computationally determined permeability against the Kozeny-Carman analytical estimate for the given packing geometry and report the relative validation error as a percentage.

### 2. `convergence.png` — grid convergence diagnostic plot
### 3. `regime.png` — pressure-velocity regime diagnostic plot

Both plots must be generated using `gnuplot`. Save the corresponding gnuplot scripts as `/app/convergence.gp` and `/app/regime.gp`.

All quantities in SI units.