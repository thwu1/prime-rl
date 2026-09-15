The `/app/` directory is a git repository containing the `frame3d` Python package for 3D structural frame analysis. The package includes a complete linear static solver — elastic stiffness assembly, load vector construction, boundary condition handling, and displacement solving. Your task is to extend it with eigenvalue buckling analysis capability.

## Prerequisites

The package currently fails to import due to a source file removed in a recent git commit. Diagnose and fix this using the repository's git history before proceeding with the implementation.

## Task

Implement the three stub functions in `/app/frame3d/buckling.py`:
- `local_geometric_stiffness_3d`
- `assemble_global_geometric_stiffness`
- `eigenvalue_buckling_solve`

These complete the pipeline so that `elastic_critical_load()` (defined in `/app/frame3d/analysis.py`) returns correct results. The existing modules `/app/frame3d/elastic.py` and `/app/frame3d/solve.py` are complete and functional — study them to understand the package's conventions, data structures, DOF ordering, and available utilities.

## Verification

Tests import `elastic_critical_load` from the `frame3d` package and `local_geometric_stiffness_3d` from `frame3d.buckling`.

**Local geometric stiffness matrix (`local_geometric_stiffness_3d`):**
- Must return a 12x12 symmetric NumPy array
- Must be identically zero when all force and moment inputs are zero
- Entries depending solely on the axial force parameter must scale linearly when that parameter is doubled (checked at DOF indices [0,0], [1,1], and [3,3])
- Transverse diagonal entries under compressive axial load must be smaller than under equal-magnitude tensile load (checked at indices [1,1] and [3,3])
- All 12 diagonal entries and 10 specific off-diagonal entries under pure axial load (Fx2 only, with unit parameters L=A=I_rho=1) are compared against closed-form expressions from standard 3D beam element references
- 12 moment-coupling entries — including moment-displacement, moment-rotation, torsion-bending, and polar-inertia coupling — are verified with parameters L=2.0, A=0.01, I_rho=5e-6, and non-zero values for all force/moment inputs (Fx2=1000, Mx2=200, My1=50, Mz1=-75, My2=-25, Mz2=100)

**Full pipeline (`elastic_critical_load`):**
- Verified against analytical Euler buckling loads for cantilever columns with circular cross-sections, across radii {0.5, 0.75, 1.0} and lengths {10.0, 20.0, 40.0}, with E=1000, nu=0.3, and 10 elements per column. Required relative error: below 1e-5 per configuration.
- Monotonic mesh convergence: relative error must decrease across refinement levels {10, 20, 30, 40} elements for a fixed cantilever (L=20, r=1.0). The finest mesh must achieve relative error below 1e-6.
- Orientation invariance: critical load factor must match (rtol=1e-9) between the original column and a copy rigidly rotated 35 degrees about the axis [2, -1, 0.5].