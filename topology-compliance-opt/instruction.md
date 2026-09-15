Implement a 2D topology optimization solver that minimizes structural compliance of a cantilever beam under the SIMP (Solid Isotropic Material with Penalization) framework. The full problem definition — mesh dimensions, material properties, boundary conditions, optimization parameters, and required output format — is in `/app/problem.json`.

The solver must use bilinear quadrilateral (Q4) finite elements under plane stress assumptions, density filtering, and an optimality criteria (OC) update scheme. No external finite element or topology optimization libraries are permitted; NumPy and SciPy may be used for linear algebra and sparse matrix operations only.

Write output files to `/app/results/` as specified in `problem.json`.