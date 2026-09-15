The file `/app/system_spec.md` defines a 4-species stiff chemical kinetics system with time-dependent rate modulation and discrete reactant injection events. The C source `/app/robertson_ext.c` implements the derivative function and initialization routines for deSolve's compiled-code interface but has no analytical Jacobian. R, gcc, and the deSolve package are pre-installed.

Derive and implement the full 4×4 analytical Jacobian in C following deSolve's compiled-code Jacobian interface, then design a complete R solver driver that correctly configures forcing function interpolation from `/app/forcing_data.csv`, discrete injection events, and error tolerances appropriate for the system's structure. The rate constants span 10 orders of magnitude and species y2 is a fast reactive intermediate whose concentration remains orders of magnitude below the other species — both have implications for solver and tolerance selection.

Benchmark at least three distinct solver configurations — varying integration method and/or Jacobian strategy — using deSolve's integration diagnostics (steps taken, function evaluations, Jacobian evaluations). Select the most efficient configuration that produces accurate results.

## Required Output

- `/app/robertson_ext.so` — compiled shared library exporting both `derivs` and `jac` symbols
- `/app/results.csv` — solution from the best configuration, columns: time, y1, y2, y3, y4
- `/app/benchmark.csv` — solver comparison data, columns: solver, nsteps, nfevls, njevls