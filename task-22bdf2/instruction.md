Scenario configs in `/app/scenarios/` define 2D incompressible fluid flow problems over rectangular domains. Build a solver invokable as:

```
python3 /app/solver.py <config.toml> <output.npz>
```

## Config Structure

Each `.toml` contains: `[grid]` (`numX`, `numY`, `h`), `[physics]` (`density`, `gravity`, `dt`, `num_iters`, `over_relaxation`), `[boundary]` (`type`, `inflow_velocity`), `[obstacle]` (`enabled`, plus geometry parameters — inspect each config), `[smoke]` (`enabled`, `source_j_min`, `source_j_max`), `[simulation]` (`num_steps`).

Boundary types: **wind_tunnel** — solid walls on left/bottom/top, open right, prescribed horizontal inflow velocity maintained each step. **tank** — solid walls on left/right/bottom, open top.

One scenario defines its obstacle via a Wavefront OBJ mesh file specifying a 2D polygon.

## Output Format

`output.npz` must contain flat `float64` arrays of length `(numX+2)*(numY+2)` — grid dimensions padded by 2 for boundary cells:

- `u` — horizontal velocity on left face of each cell
- `v` — vertical velocity on bottom face of each cell
- `p` — pressure at cell centers
- `s` — cell type (0.0=solid, 1.0=fluid)
- `m` — smoke density (1.0=clear, 0.0=saturated)
- `numX`, `numY` (int) — padded dimensions (config values + 2)
- `h` (float) — cell spacing

Flat index for element `(i, j)`: `i * numY + j`.

## Success Criteria

1. Velocity field approximately divergence-free at interior fluid cells
2. Solid boundaries enforce zero normal velocity; inlets maintain prescribed inflow
3. Obstacles from configs correctly rasterized as solid cells (`s=0.0`)
4. Smoke field remains within [0, 1]
5. Closed tank under gravity reaches hydrostatic equilibrium: near-zero velocities, pressure increasing with depth
6. Numerically stable across all scenarios