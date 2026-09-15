# MAC Grid Fluid Solver Specification

## Staggered Grid Layout

The domain is discretized into a uniform grid with cell spacing `h`. The config specifies `numX` and `numY` as *interior* cell counts. The solver must add 2 ghost cells to each dimension, making the padded array dimensions `(numX+2) × (numY+2)`. All array references below use these padded dimensions.

Velocity components are stored on cell faces (staggered / MAC grid):
- `u[i,j]` — horizontal velocity at the left vertical face of cell `(i,j)`, at position `(i·h, (j+0.5)·h)`
- `v[i,j]` — vertical velocity at the bottom horizontal face of cell `(i,j)`, at position `((i+0.5)·h, j·h)`

Scalar fields (pressure `p`, solid mask `s`, smoke `m`) are at cell centers `((i+0.5)·h, (j+0.5)·h)`.

## Array Storage

All fields are stored as **flat arrays** of length `numX × numY` (padded dimensions). Element `(i,j)` maps to flat index `i * numY + j` (column-major).

## Solid Mask

`s[i,j] = 1.0` for fluid cells, `0.0` for solid cells (walls, obstacles).

## Smoke Field

`m[i,j] = 1.0` means clear (no smoke), `0.0` means full smoke. Initialized to 1.0 everywhere.

## Simulation Loop

Each time step executes these stages **in order**:

### 1. Gravity Integration

For `i` in `[1, numX)` and `j` in `[1, numY-1)`:
  if `s[i,j] ≠ 0` **and** `s[i,j-1] ≠ 0`:
    `v[i,j] += gravity × dt`

Only v-velocities between two fluid cells are affected.

### 2. Pressure Projection (Gauss-Seidel with SOR)

Reset `p` to zero.

Compute `cp = density × h / dt`.

Repeat for `numIters` iterations:
  For `i` in `[1, numX-1)`, `j` in `[1, numY-1)`:
    Skip if `s[i,j] == 0`.
    `sx0 = s[i-1,j]`, `sx1 = s[i+1,j]`, `sy0 = s[i,j-1]`, `sy1 = s[i,j+1]`
    `S = sx0 + sx1 + sy0 + sy1`. Skip if `S == 0`.
    `div = u[i+1,j] - u[i,j] + v[i,j+1] - v[i,j]`
    `Δp = (-div / S) × overRelaxation`
    `p[i,j] += cp × Δp`
    `u[i,j]   -= sx0 × Δp`
    `u[i+1,j] += sx1 × Δp`
    `v[i,j]   -= sy0 × Δp`
    `v[i,j+1] += sy1 × Δp`

### 3. Boundary Extrapolation

Copy boundary velocities from adjacent interior cells:
  For all `i`: `u[i,0] = u[i,1]`; `u[i,numY-1] = u[i,numY-2]`
  For all `j`: `v[0,j] = v[1,j]`; `v[numX-1,j] = v[numX-2,j]`

### 4. Velocity Advection (Semi-Lagrangian)

Copy `u` and `v` to temporary arrays `newU`, `newV`.

For `i` in `[1, numX)`, `j` in `[1, numY)`:

  **u-component** (if `s[i,j] ≠ 0` and `s[i-1,j] ≠ 0` and `j < numY-1`):
    Position of this u sample: `pos = (i·h, j·h + h/2)`
    Local velocity: `(u[i,j], avgV(i,j))`
      where `avgV(i,j) = (v[i-1,j] + v[i,j] + v[i-1,j+1] + v[i,j+1]) / 4`
    Backtrace: `prev = pos - dt × velocity`
    `newU[i,j] = sampleField(prev.x, prev.y, U_FIELD)`

  **v-component** (if `s[i,j] ≠ 0` and `s[i,j-1] ≠ 0` and `i < numX-1`):
    Position of this v sample: `pos = (i·h + h/2, j·h)`
    Local velocity: `(avgU(i,j), v[i,j])`
      where `avgU(i,j) = (u[i,j-1] + u[i,j] + u[i+1,j-1] + u[i+1,j]) / 4`
    Backtrace: `prev = pos - dt × velocity`
    `newV[i,j] = sampleField(prev.x, prev.y, V_FIELD)`

Replace `u` with `newU`, `v` with `newV`.

### 5. Smoke Advection

Copy `m` to `newM`.

For `i` in `[1, numX-1)`, `j` in `[1, numY-1)`:
  if `s[i,j] ≠ 0`:
    Cell center: `pos = (i·h + h/2, j·h + h/2)`
    Velocity at center: `u_avg = (u[i,j] + u[i+1,j])/2`, `v_avg = (v[i,j] + v[i,j+1])/2`
    Backtrace: `prev = pos - dt × (u_avg, v_avg)`
    `newM[i,j] = sampleField(prev.x, prev.y, S_FIELD)`

Replace `m` with `newM`.

## Bilinear Field Sampling

`sampleField(x, y, field)`:

1. Clamp: `x = clamp(x, h, numX·h)`, `y = clamp(y, h, numY·h)`
2. Field-dependent offset `(dx, dy)`:
   - U_FIELD: `dx=0, dy=h/2`
   - V_FIELD: `dx=h/2, dy=0`
   - S_FIELD (smoke): `dx=h/2, dy=h/2`
3. Grid coords:
   `x0 = min(floor((x-dx)/h), numX-1)`, `x1 = min(x0+1, numX-1)`
   `y0 = min(floor((y-dy)/h), numY-1)`, `y1 = min(y0+1, numY-1)`
4. Weights:
   `tx = ((x-dx) - x0·h) / h`, `ty = ((y-dy) - y0·h) / h`
   `sx = 1-tx`, `sy = 1-ty`
5. Interpolate:
   `result = sx·sy·f[x0,y0] + tx·sy·f[x1,y0] + tx·ty·f[x1,y1] + sx·ty·f[x0,y1]`

## Boundary Setup

### Wind Tunnel (`type = "wind_tunnel"`)
- Solid walls: `i=0` (left), `j=0` (bottom), `j=numY-1` (top) — using padded numY
- All other cells are fluid
- Initial and per-step: set `u[1,j] = inflow_velocity` for all `j`
- If smoke enabled: per-step, set `m[0,j] = 0.0` for `j` in `[source_j_min, source_j_max)`

### Tank (`type = "tank"`)
- Solid walls: `i=0` (left), `i=numX-1` (right), `j=0` (bottom) — padded dims
- Top boundary is free (fluid)

### Obstacle
If enabled, mark cells as solid where the cell center is within the obstacle radius:
  `dist = sqrt(((i+0.5)·h - center_x)² + ((j+0.5)·h - center_y)²)`
  If `dist < radius`: `s[i,j] = 0.0`

## Per-Step Inflow Maintenance

For wind tunnel: **before** each simulation step, re-apply inflow velocity and smoke source (values above). This ensures boundary conditions are maintained throughout the simulation.
