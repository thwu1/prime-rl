A DOLFINx finite element solver at `/app/kovasznay.py` computes steady Kovasznay flow -- an exact solution to the incompressible Navier-Stokes equations at Reynolds number 25 -- using Taylor-Hood (P2-P1) elements with Picard (fixed-point) linearization for the convective nonlinearity. The solver contains multiple bugs and produces incorrect results.

Debug and fix `/app/kovasznay.py` so that running `python3 /app/kovasznay.py` writes `/app/results.json` with L2 velocity error (`e_u`) below 5e-3 and L2 pressure error (`e_p`) below 5e-2 compared to the known exact Kovasznay solution.

The DOLFINx FEM library, PETSc with MUMPS direct solver, and MPI are pre-installed via conda at `/opt/conda`.