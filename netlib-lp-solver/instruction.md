Build a complete pipeline to decompress, parse, and solve Netlib LP benchmark problems from scratch.

The compressed Netlib LP benchmark files are in `/app/compressed/` and the C source for the standard Netlib decompressor (`emps`) is at `/app/emps.c`. No pre-built binaries or decompressed files are provided.

Your pipeline must:

- Compile `emps.c` into a working binary using `gcc`, then use it to decompress each compressed benchmark file into standard MPS format. Store the decompressed files in `/app/problems/` with `.mps` extensions (e.g., `/app/problems/afiro.mps`). The decompressor reads from stdin and writes to stdout.

- Implement a linear programming solver that parses standard MPS fixed-column format and solves LP problems to optimality via a simplex method. Using existing LP solver libraries (scipy.optimize.linprog, PuLP, CVXPY, Gurobi, CPLEX, OR-Tools, GLPK, HiGHS, etc.) is prohibited. Basic linear algebra via numpy/scipy (matrix solve, factorization) is permitted.

- Write results to `/app/results.json` as a JSON object mapping each problem name (lowercase) to its computed optimal objective value. All five problems must be solved correctly within 0.01% relative error of the known Netlib reference values.

The five benchmark problems are: AFIRO, SC50B, KB2, SHARE2B, ADLITTLE. Reference optimal values are published in the Netlib LP/data README (from MINOS 5.3).