A 2D structured-grid reservoir model is provided in `/app/input/`. The reservoir has heterogeneous, anisotropic permeability (three orders of magnitude contrast), non-uniform cell spacing, four volumetric-rate-controlled wells (two injectors, two producers), and sealed (no-flow) boundaries on all sides. A reference pressure at one cell anchors the solution.

Build a numerical pressure solver that correctly computes the steady-state single-phase pressure field governed by Darcy's law and mass conservation:

    div( (K / mu) * grad(p) ) = q

The solver must be executable as `python3 /app/solver.py [input_dir] [output_dir]` (defaulting to `/app/input` and `/app/output`) and must produce the output files described in `/app/spec.txt`.

The permeability field contains a high-permeability channel, a low-permeability barrier, and strong directional anisotropy. The grid uses geometric grading with significant cell-size variation. Your discretization must handle these features physically — naive approaches to inter-cell flux computation in heterogeneous media produce order-of-magnitude errors in the pressure solution.