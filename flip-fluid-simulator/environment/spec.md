# Hybrid Particle-Grid Fluid Simulation — Mathematical Specification

## 1. Overview

The Fluid-Implicit-Particle (FLIP) method is a hybrid Eulerian-Lagrangian
scheme for incompressible fluid simulation. Lagrangian particles carry
velocity and are advected through an Eulerian Marker-and-Cell (MAC)
staggered grid where pressure projection enforces the divergence-free
condition. A PIC/FLIP blend controls numerical diffusion.

## 2. Domain and Grid

The simulation domain is a rectangle [0, W] x [0, H] discretized on a
MAC staggered grid.

### Grid Dimensions

Given a spacing parameter s:

    fNumX = floor(W / s) + 1
    fNumY = floor(H / s) + 1
    h     = max(W / fNumX,  H / fNumY)
    fInvSpacing = 1 / h
    fNumCells   = fNumX * fNumY

### MAC Staggered Layout

Velocity components live at cell face centers, scalars at cell centers:

  * u (horizontal velocity): at left vertical faces.
    u(i,j) is at position (i*h, (j + 0.5)*h).
  * v (vertical velocity): at bottom horizontal faces.
    v(i,j) is at position ((i + 0.5)*h, j*h).
  * Scalars (pressure p, cell type, particle density, solid flag s):
    at cell centers ((i + 0.5)*h, (j + 0.5)*h).

Index mapping (column-major): cell(i, j) -> i * fNumY + j.

All grid arrays have length fNumCells.

### Cell Types

    FLUID = 0   -- contains fluid particles
    AIR   = 1   -- empty
    SOLID = 2   -- wall / boundary

The solid flag array s determines boundaries: s(cell) = 0 -> SOLID,
s(cell) != 0 -> passable.

## 3. Particle System

Particles are Lagrangian tracers stored in interleaved arrays:

    particlePos:  [x0, y0, x1, y1, ...]   length 2 * maxParticles
    particleVel:  [vx0, vy0, vx1, vy1, ...] length 2 * maxParticles

Particle i has position (particlePos[2i], particlePos[2i+1]) and
velocity (particleVel[2i], particleVel[2i+1]).

### Spatial Hashing Grid (for particle separation)

    pInvSpacing = 1 / (2.2 * particleRadius)
    pNumX       = floor(W * pInvSpacing) + 1
    pNumY       = floor(H * pInvSpacing) + 1
    pNumCells   = pNumX * pNumY

## 4. Simulation Pipeline

Each call to simulate(dt, gravity, flipRatio, numPressureIters,
numParticleIters, overRelaxation, compensateDrift, separateParticles)
executes the following pipeline with timestep sdt = dt.

### 4.1. Particle Integration (semi-implicit Euler)

For each particle i:

    vy_i  <-  vy_i + sdt * gravity
    x_i   <-  x_i  + vx_i * sdt
    y_i   <-  y_i  + vy_i * sdt

### 4.2. Particle Separation (if separateParticles is true)

Use a counting-sort spatial hash to identify nearby particles, then push
overlapping pairs apart.

Counting phase: For each particle, compute hash cell:

    xi = clamp(floor(x * pInvSpacing), 0, pNumX - 1)
    yi = clamp(floor(y * pInvSpacing), 0, pNumY - 1)
    cellNr = xi * pNumY + yi

Increment numCellParticles[cellNr].

Reverse prefix sum: Accumulate counts into firstCellParticle:

    first = 0
    for c = 0 .. pNumCells-1:
        first += numCellParticles[c]
        firstCellParticle[c] = first
    firstCellParticle[pNumCells] = first

Fill: For each particle, decrement firstCellParticle[cellNr] and
store the particle index in cellParticleIds.

Push iterations: For numParticleIters iterations, for each
particle i at (px, py):

  * Search the 3x3 neighborhood of hash cells around (px, py).
  * For each neighbor particle j (j != i) with distance
    d = sqrt(dx^2 + dy^2) < 2*r and d > 0:
      s = 0.5 * (2r - d) / d
      Push i and j apart symmetrically by s * (dx, dy).

### 4.3. Wall Collision Handling

For each particle, clamp position to:

    x in [h + r,  (fNumX - 1)*h - r]
    y in [h + r,  (fNumY - 1)*h - r]

When a component is clamped, zero that velocity component.

### 4.4. Velocity Transfer: Particles -> Grid (P2G)

Cell classification:

    For each cell:  type = SOLID if s[cell] = 0,  else AIR
    For each particle:  mark containing grid cell as FLUID (if not SOLID)

Velocity scatter (per component c in {u, v}):

Staggering offset (accounts for the shift between the face location
and the cell corner used for indexing):

    For u (c = 0): (dx, dy) = (0,   h/2)
    For v (c = 1): (dx, dy) = (h/2, 0  )

For each particle at (px, py), clamped to [h, (fNumX-1)*h] x [h, (fNumY-1)*h]:

    x0 = min(floor((px - dx) * fInvSpacing),  fNumX - 2)
    tx = ((px - dx) - x0 * h) * fInvSpacing
    x1 = min(x0 + 1, fNumX - 2)

    y0 = min(floor((py - dy) * fInvSpacing),  fNumY - 2)
    ty = ((py - dy) - y0 * h) * fInvSpacing
    y1 = min(y0 + 1, fNumY - 2)

    sx = 1 - tx,  sy = 1 - ty

Bilinear weights and grid indices:

    w00 = sx*sy   nr0 = x0*fNumY + y0
    w10 = tx*sy   nr1 = x1*fNumY + y0
    w11 = tx*ty   nr2 = x1*fNumY + y1
    w01 = sx*ty   nr3 = x0*fNumY + y1

Accumulate:  f[nrk] += particleVel[2i + c] * wk
             weights[nrk] += wk

Normalize: f[cell] /= weights[cell]  where weights[cell] > 0.

Restore solid boundaries: For each cell (i, j):
  * If cell is SOLID or left neighbor (i-1, j) is SOLID: u(i,j) = prevU(i,j)
  * If cell is SOLID or bottom neighbor (i, j-1) is SOLID: v(i,j) = prevV(i,j)

### 4.5. Particle Density Update

Splat unit density from each particle onto the grid using bilinear
interpolation at cell-center positions (offset h/2 from both axes):

For each particle at (x, y), clamped to [h, (fNumX-1)*h]:

    x0 = floor((x - h/2) * fInvSpacing)
    tx = ((x - h/2) - x0*h) * fInvSpacing
    x1 = min(x0 + 1, fNumX - 2)

    (similarly for y)

    Splat 1.0 with bilinear weights to cells (x0,y0), (x1,y0),
    (x1,y1), (x0,y1), guarded by bounds checks.

If particleRestDensity = 0 (first call), set it to the mean density
over all FLUID cells.

### 4.6. Pressure Projection

Initialize pressure array p to zero. Save current u, v as prevU, prevV.

Pressure coefficient: cp = density * h / sdt.

For each iteration (up to numPressureIters):

  For each interior fluid cell (i, j) where 1 <= i < fNumX-1,
  1 <= j < fNumY-1:

    s_L = s[left],  s_R = s[right],  s_B = s[bottom],  s_T = s[top]
    S = s_L + s_R + s_B + s_T
    If S = 0: skip

    div = u(i+1, j) - u(i, j) + v(i, j+1) - v(i, j)

    If compensateDrift and particleRestDensity > 0:
        compression = particleDensity(i, j) - particleRestDensity
        if compression > 0:  div -= compression

    Pressure correction:  pCorr = -(div / S) * overRelaxation

    Update face velocities:
        u(i,j)     -= s_L * pCorr
        u(i+1, j)  += s_R * pCorr
        v(i, j)    -= s_B * pCorr
        v(i, j+1)  += s_T * pCorr

    Accumulate:  p(i,j) += cp * pCorr

### 4.7. Velocity Transfer: Grid -> Particles (G2P)

For each particle and each velocity component c:

  * Compute bilinear weights as in section 4.4 (same staggering offsets).
  * Determine face validity: a grid velocity at index nr is valid
    if either cell adjacent to that face is non-AIR.
      For u (c = 0): offset = fNumY.
          valid iff cellType[nr] != AIR or cellType[nr - fNumY] != AIR.
      For v (c = 1): offset = 1.
          valid iff cellType[nr] != AIR or cellType[nr - 1] != AIR.

  * Weighted valid denominator: D = sum(validk * wk)
  * If D > 0:
      PIC velocity:   v_PIC  = sum(validk * wk * fk) / D
      FLIP correction: v_corr = sum(validk * wk * (fk - prevFk)) / D
      v_FLIP = v_old + v_corr
      Final:  v_particle = (1 - flipRatio) * v_PIC  +  flipRatio * v_FLIP

## 5. C Library API

Build a shared library libflip.so with an opaque handle for the
simulation state. Required entry points:

  * Creation: accepts (density, width, height, spacing, particleRadius,
    maxParticles), returns handle.
  * Simulation step: accepts handle + all simulate parameters.
  * Accessor functions for every grid/particle array and scalar listed
    in the Python stub.
  * Destructor: frees all memory.
