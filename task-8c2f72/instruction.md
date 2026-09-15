A working serial 2D Poisson solver at `/app/solver_serial.c` computes the numerical solution to −∇²u = 2π²sin(πx)sin(πy) on the unit square with homogeneous Dirichlet boundary conditions on a 32×32 interior grid.

A skeleton file at `/app/solver_parallel.c` contains MPI initialization boilerplate and header comments documenting the implementation constraints and required output schema. Complete this skeleton so it compiles, runs correctly with 4 MPI processes, and produces numerically accurate results in `/app/results.json` matching the schema specified in its header.

Build and run: `make solver_parallel && make run_parallel`. Serial reference: `make solver_serial && make run_serial`.