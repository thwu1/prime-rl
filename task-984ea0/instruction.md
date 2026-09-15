A two-layer simulation framework at `/app/` couples C finite-difference kernels (`/app/src/kernels.c`, API in `/app/src/kernels.h`) with a Python driver (`/app/solver.py`) via `ctypes`. Both layers are incomplete: the C kernels are stubbed and the Python driver has placeholder logic. A Makefile at `/app/src/Makefile` builds the shared library `/app/src/libkernels.so`.

Reference solutions are in `/app/data/reference.h5`. The HDF5 internal structure is undocumented; `hdf5-tools` is installed for inspection. Run `python3 /app/evaluate.py` to check accuracy.

## Governing Equations

1D compressible Navier-Stokes on periodic domain [-1, 1]:

- **Continuity:** dρ/dt + d(ρv)/dx = 0
- **Momentum:** ρ(dv/dt + v dv/dx) = -dp/dx + η d²v/dx² + (ζ + η/3) d(dv/dx)/dx
- **Energy:** dE/dt + d[(E+p)v - v σ']/dx = 0

E = p/(Γ-1) + ρv²/2 is total energy, Γ = 5/3, σ' = (ζ + 4η/3) dv/dx is viscous stress. Grid is vertex-centered: N points from -1 to 1 with endpoints coinciding under periodicity, dx = 2/(N-1).

## Acceptance Criteria

- `/app/src/libkernels.so` compiled and exporting required symbols
- nRMSE < 0.05 against reference for both high-viscosity (η=ζ=0.1) and low-viscosity (η=ζ=0.01) regimes
- Spatial convergence rate > 1.3 across grid refinement
- No NaN values; correct output shapes; initial conditions preserved at t=0