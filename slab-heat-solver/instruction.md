Implement a solver at `/app/solver.py` that computes steady-state 2D ground-coupled heat transfer for slab-on-grade buildings with heterogeneous soil and perimeter insulation, then extracts the linear thermal transmittance (psi-value) characterizing the thermal bridge at the slab edge.

The solver must read configurations from `/app/cases.json` and write results to `/app/results.json`. The physical setup, governing equation, boundary conditions, and output specifications are described in `/app/problem_spec.txt`.

## Cases

Eight test cases are defined in `cases.json`. The solver must produce results for all eight:

- **GC_BASE**: Baseline 12m slab, 15m depth, homogeneous soil k=1.9 W/(m·K)
- **GC_NARROW**: Narrow 6m slab (higher perimeter-to-area ratio)
- **GC_WIDE**: Wide 20m slab (lower perimeter-to-area ratio)
- **GC_HIGHK**: Doubled soil conductivity k=3.8 W/(m·K)
- **GC_SHALLOW**: Shallow 5m depth boundary
- **GC_LAYER**: Two-layer soil (upper k=1.9, lower k=0.5)
- **GC_VINSUL**: Vertical perimeter insulation (k=0.04)
- **GC_COMBO**: Layered soil with vertical perimeter insulation

## Output Format

Write `/app/results.json` with each case keyed by name. Every case must include three positive floating-point values:

```json
{
    "CASE_NAME": {
        "heat_loss_per_meter": <float>,
        "flux_density_avg": <float>,
        "psi_value": <float>
    }
}
```

## Internal Consistency Requirements

The three output quantities must be mutually consistent:

- `flux_density_avg` must equal `heat_loss_per_meter / (2 * slab_half_width)` within 0.1% relative error.
- `psi_value` must equal `heat_loss_per_meter / delta_T - U_1d * 2 * slab_half_width` within 0.1% relative error, where `U_1d = 1 / sum(d_i / k_i)` is the one-dimensional thermal transmittance through the soil column (computed from soil layers only, not insulation), and `delta_T = T_indoor - T_outdoor`.
- All three values must be strictly positive for every case (edge effects always increase heat loss beyond the 1D prediction, so psi is always positive).

## Accuracy Tolerances

**Homogeneous cases** (GC_BASE, GC_NARROW, GC_WIDE, GC_HIGHK, GC_SHALLOW): `heat_loss_per_meter` and `flux_density_avg` within 1.5% of analytical reference values; `psi_value` within 3%.

**Layered soil case** (GC_LAYER): `heat_loss_per_meter` and `flux_density_avg` within 2%; `psi_value` within 5%.

**Insulation cases** (GC_VINSUL, GC_COMBO): no closed-form reference, but must satisfy physical consistency bounds (see below).

## Cross-Case Physical Consistency

The following physical relationships must hold across cases:

- **Conductivity linearity**: Since the governing Laplace equation is linear in k, `Q_HIGHK / Q_BASE` must be within 0.05 of 2.0 (absolute).
- **Slab width monotonicity**: `Q_NARROW < Q_BASE < Q_WIDE` (total heat loss increases with slab width).
- **Flux density perimeter effect**: `flux_density_NARROW > flux_density_BASE > flux_density_WIDE` (narrower slabs have higher average flux density due to perimeter dominance).
- **Shallow depth effect**: `Q_SHALLOW > Q_BASE` (shallower ground boundary = less thermal resistance).
- **Layered soil effect**: `Q_LAYER < Q_BASE` (low-k deep layer increases total thermal resistance).

## Insulation Physics Constraints

- GC_VINSUL: heat loss reduced by more than 5% compared to GC_BASE, but remains above 30% of GC_BASE (insulation cannot eliminate all heat loss).
- GC_COMBO: heat loss less than both GC_LAYER and GC_BASE.
- GC_VINSUL: psi-value less than GC_BASE psi-value.
- GC_COMBO: psi-value less than GC_LAYER psi-value.