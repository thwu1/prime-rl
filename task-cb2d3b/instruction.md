A 2D compressible Euler finite volume solver is provided at `/app/euler2d.py`. Extend it to solve the **ideal magnetohydrodynamics (MHD) equations** and simulate the **Orszag-Tang vortex** problem. The solver must maintain the solenoidal constraint (div B = 0) to machine precision throughout the evolution.

## Simulation Parameters

- Grid: 128x128, periodic, domain [0,1]^2
- gamma = 5/3, CFL factor = 0.4, slope limiting enabled
- Final time: t = 0.5
- Initial conditions:
  - rho = gamma^2 / (4*pi)
  - vx = -sin(2*pi*y), vy = sin(2*pi*x)
  - P_gas = gamma / (4*pi)
  - Magnetic vector potential at cell corner nodes (x_node = k*dx, k=1..N): Az = cos(4*pi*x) / (4*pi*sqrt(4*pi)) + cos(2*pi*y) / (2*pi*sqrt(4*pi))
  - Derive initial B from the curl of Az
  - Total pressure: P = P_gas + 0.5*(Bx^2 + By^2)

## Deliverables

### Build system

Create a `Makefile` at `/app/Makefile` with these targets:
- `run` — executes the MHD simulation
- `plots` — generates diagnostic plots (depends on `run`)
- `all` — runs both `run` and `plots`
- `clean` — removes `/app/output/`

The Makefile must be syntactically valid (i.e., `make -n all` succeeds).

### HDF5 output

Save a single HDF5 file `/app/output/results.h5` containing these datasets:

| Dataset           | Shape      | Description                                          |
|-------------------|------------|------------------------------------------------------|
| `density`         | (128,128)  | Final density field                                  |
| `divB`            | (128,128)  | Final discrete divergence of B                       |
| `Bx`              | (128,128)  | Final cell-averaged Bx                               |
| `By`              | (128,128)  | Final cell-averaged By                               |
| `mass_history`    | (N_steps,) | Total mass at each timestep (must have >50 entries)  |
| `energy_history`  | (N_steps,) | Total energy at each timestep                        |

The HDF5 structure must be verifiable with `h5ls /app/output/results.h5`, which should list all six datasets above.

Also save `/app/output/params.json` with exactly: `{"N": 128, "gamma": 1.6666666666666667, "tEnd": 0.5, "courant_fac": 0.4}`

### Diagnostic plots (gnuplot)

Generate PNG plots using `gnuplot` (not matplotlib):
- `/app/output/density_contour.png` — filled contour of the final density field
- `/app/output/divB_map.png` — map of the divergence of B

Save the gnuplot scripts at `/app/output/density.gp` and `/app/output/divB.gp`. Each script must be a valid self-contained gnuplot file (containing `set terminal` directives). The resulting PNG files must be non-trivial (>100 bytes).

## Correctness Criteria

1. **Solenoidal constraint**: max|div B| < 1e-10
2. **Conservation**: Relative change in total mass and total energy must remain < 1e-10 throughout the entire simulation
3. **Density field**: Strictly positive; std(rho) > 0.01; max(rho) > 0.25; min(rho) < 0.20
4. **Mean density**: Must equal gamma^2/(4*pi) to relative error < 1e-6
5. **Rotational symmetry**: The Orszag-Tang vortex has 180-degree rotational symmetry — rho[i,j] must equal rho[N-1-i, N-1-j] to precision < 1e-8
6. **Magnetic field**: mean(B^2) > 1e-4; max(B^2) < 10; antisymmetric under 180-degree rotation (B[i,j] = -B[N-1-i, N-1-j]) to precision < 1e-8
7. **Magnetic energy fraction**: 0.05 < integral(0.5*B^2*dV) / E_total < 0.6