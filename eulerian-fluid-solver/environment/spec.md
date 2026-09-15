# 2D Eulerian Incompressible Fluid Simulator — MAC Grid Method

## Overview

Implement a 2D incompressible fluid simulator using the Marker-and-Cell (MAC) staggered grid method. The simulator uses a Gauss-Seidel iterative solver with successive over-relaxation (SOR) for pressure projection, and semi-Lagrangian advection for velocity and passive scalar (smoke) transport.

## Data Layout

### Grid Structure

The simulation domain is discretized on a regular Cartesian grid with cell spacing `h`. The grid has `numX × numY` cells, where `numX = user_numX + 2` and `numY = user_numY + 2` (the extra 2 cells per dimension serve as boundary ghost cells).

All field arrays are stored as **1D arrays** with column-major-like index mapping:

    index(i, j) = i × numY + j

where `i ∈ [0, numX)` is the column index (horizontal) and `j ∈ [0, numY)` is the row index (vertical).

### Staggered Field Locations

Velocities are stored on cell **faces**, while scalar quantities are stored at cell **centers**:

| Field | Location | World Position |
|-------|----------|----------------|
| `u[i,j]` (horizontal velocity) | Left face of cell (i,j) | `(i·h, j·h + h/2)` |
| `v[i,j]` (vertical velocity) | Bottom face of cell (i,j) | `(i·h + h/2, j·h)` |
| `p[i,j]` (pressure) | Cell center | `((i+0.5)·h, (j+0.5)·h)` |
| `s[i,j]` (solid flag) | Cell center | 0.0 = solid, 1.0 = fluid |
| `m[i,j]` (smoke density) | Cell center | 0.0 = full smoke, 1.0 = clear |

## Class API: `EulerianFluid`

### Constructor: `__init__(self, density, num_x, num_y, h)`

Parameters:
- `density` (float): fluid density (e.g. 1000.0)
- `num_x`, `num_y` (int): number of interior cells per dimension
- `h` (float): cell spacing

Store `numX = num_x + 2`, `numY = num_y + 2`, `numCells = numX × numY`.

Initialize 1D arrays of length `numCells`:
- `u`, `v`, `p`, `s`: all zeros
- `m`: all ones (clear air everywhere)

Also allocate temporary arrays `newU`, `newV`, `newM` (same size, zeros).

### `setup_wind_tunnel(self, inlet_velocity)`

Configure boundary conditions for a wind tunnel:

1. For every cell (i, j): set `s[i,j] = 1.0` (fluid).
2. Override to solid (`s = 0.0`): left wall (`i = 0`), bottom wall (`j = 0`), top wall (`j = numY − 1`). The right boundary remains fluid (open outflow).
3. Set inlet horizontal velocity: `u[1, j] = inlet_velocity` for all j.
4. Set smoke source at inlet: `m[0, j] = 0.0` for j in a vertical band of height `floor(0.1 × numY)` centered at `j = numY / 2`.

### `set_obstacle(self, cx, cy, radius)`

For each interior cell (i, j) with i ∈ [1, numX−1) and j ∈ [1, numY−1):
- Compute cell center position: `px = (i + 0.5)·h`, `py = (j + 0.5)·h`
- If `(px − cx)² + (py − cy)² < radius²`:
  - Mark solid: `s[i,j] = 0.0`
  - Clear smoke: `m[i,j] = 1.0`
  - Zero adjacent velocity components: `u[i,j] = 0`, `u[i+1,j] = 0`, `v[i,j] = 0`, `v[i,j+1] = 0`

### `integrate(self, dt, gravity)`

Apply gravitational acceleration to the vertical velocity field.

For each i ∈ [1, numX) and j ∈ [1, numY−1):
- If cell (i, j) is fluid **and** cell (i, j−1) is fluid (both `s ≠ 0`):
  - `v[i,j] += gravity · dt`

### `solve_incompressibility(self, num_iters, dt, over_relaxation)`

Gauss-Seidel pressure projection with successive over-relaxation (SOR). This method does **not** reset the pressure field — that is done by `simulate()`.

Compute the pressure coefficient: `cp = density · h / dt`.

For each Gauss-Seidel iteration (total: `num_iters`), sweep over all interior cells i ∈ [1, numX−1), j ∈ [1, numY−1):

1. Skip if cell (i, j) is solid (`s[i,j] = 0`).
2. Read neighbor fluid flags: `sx0 = s[i−1,j]`, `sx1 = s[i+1,j]`, `sy0 = s[i,j−1]`, `sy1 = s[i,j+1]`.
3. Compute `s_total = sx0 + sx1 + sy0 + sy1`. Skip if `s_total = 0`.
4. Compute discrete divergence:
   `div = u[i+1,j] − u[i,j] + v[i,j+1] − v[i,j]`
5. Pressure correction:
   `p_corr = −over_relaxation · div / s_total`
6. Accumulate pressure: `p[i,j] += cp · p_corr`
7. Update velocity faces:
   - `u[i,j]   −= sx0 · p_corr`
   - `u[i+1,j] += sx1 · p_corr`
   - `v[i,j]   −= sy0 · p_corr`
   - `v[i,j+1] += sy1 · p_corr`

### `extrapolate(self)`

Copy boundary velocities from adjacent interior cells:
- For all i ∈ [0, numX): `u[i, 0] = u[i, 1]` and `u[i, numY−1] = u[i, numY−2]`
- For all j ∈ [0, numY): `v[0, j] = v[1, j]` and `v[numX−1, j] = v[numX−2, j]`

### `sample_field(self, x, y, field_type)`

Bilinear interpolation of a field value at world position (x, y).

**Field types** (passed as strings):
- `'u'` → interpolate from `u` array, offset `(dx, dy) = (0, h/2)`
- `'v'` → interpolate from `v` array, offset `(dx, dy) = (h/2, 0)`
- `'smoke'` → interpolate from `m` array, offset `(dx, dy) = (h/2, h/2)`

Algorithm:
1. Clamp position: `x = clamp(x, h, numX·h)`, `y = clamp(y, h, numY·h)`
2. Compute adjusted coordinates: `x' = x − dx`, `y' = y − dy`
3. Grid indices:
   - `x0 = min(floor(x' / h), numX − 1)`, `x1 = min(x0 + 1, numX − 1)`
   - `y0 = min(floor(y' / h), numY − 1)`, `y1 = min(y0 + 1, numY − 1)`
4. Interpolation weights:
   - `tx = (x' − x0·h) / h`, `sx = 1 − tx`
   - `ty = (y' − y0·h) / h`, `sy = 1 − ty`
5. Return:
   `sx·sy · f[x0,y0] + tx·sy · f[x1,y0] + tx·ty · f[x1,y1] + sx·ty · f[x0,y1]`

### `advect_velocity(self, dt)`

Semi-Lagrangian advection: backtrack from each velocity sample point along the local velocity to find the departure point, then interpolate the old velocity at that point.

Create copies of the current velocity fields (`newU = copy(u)`, `newV = copy(v)`).

For i ∈ [1, numX), j ∈ [1, numY):

**u component** — if `s[i,j] ≠ 0` and `s[i−1,j] ≠ 0` and `j < numY − 1`:
1. Position of u[i,j]: `x = i·h`, `y = j·h + h/2`
2. Local velocity: `u_here = u[i,j]`, `v_here = avgV(i, j)`
   where `avgV(i, j) = (v[i−1,j] + v[i,j] + v[i−1,j+1] + v[i,j+1]) / 4`
3. Backtrack: `(x_bt, y_bt) = (x − dt·u_here, y − dt·v_here)`
4. `newU[i,j] = sample_field(x_bt, y_bt, 'u')`

**v component** — if `s[i,j] ≠ 0` and `s[i,j−1] ≠ 0` and `i < numX − 1`:
1. Position of v[i,j]: `x = i·h + h/2`, `y = j·h`
2. Local velocity: `u_here = avgU(i, j)`, `v_here = v[i,j]`
   where `avgU(i, j) = (u[i,j−1] + u[i,j] + u[i+1,j−1] + u[i+1,j]) / 4`
3. Backtrack: `(x_bt, y_bt) = (x − dt·u_here, y − dt·v_here)`
4. `newV[i,j] = sample_field(x_bt, y_bt, 'v')`

Replace `u` with `newU` and `v` with `newV`.

### `advect_smoke(self, dt)`

Semi-Lagrangian transport of the smoke scalar field.

Create a copy `newM = copy(m)`.

For each interior fluid cell (i ∈ [1, numX−1), j ∈ [1, numY−1)) where `s[i,j] ≠ 0`:
1. Cell center velocity (averaged from adjacent faces):
   - `u_c = (u[i,j] + u[i+1,j]) / 2`
   - `v_c = (v[i,j] + v[i,j+1]) / 2`
2. Cell center position: `x = i·h + h/2`, `y = j·h + h/2`
3. Backtrack: `(x_bt, y_bt) = (x − dt·u_c, y − dt·v_c)`
4. `newM[i,j] = sample_field(x_bt, y_bt, 'smoke')`

Replace `m` with `newM`.

### `simulate(self, dt, gravity, num_iters, over_relaxation)`

Execute one complete simulation step in this order:
1. `integrate(dt, gravity)`
2. Reset pressure field: `p[i] = 0` for all i
3. `solve_incompressibility(num_iters, dt, over_relaxation)`
4. `extrapolate()`
5. `advect_velocity(dt)`
6. `advect_smoke(dt)`

### `max_divergence(self) → float`

Return the maximum absolute discrete divergence over all interior fluid cells:

    max |u[i+1,j] − u[i,j] + v[i,j+1] − v[i,j]|

for i ∈ [1, numX−1), j ∈ [1, numY−1), where s[i,j] ≠ 0.
