Eight linear programming benchmark problems from the Netlib LP test collection are provided in Netlib compressed MPS format at `/app/data/` (files with `.cmp` extension). The C source code for the decompression utility (`emps.c`) is at `/app/data/emps.c`. The compression scheme is Netlib-proprietary -- not gzip, bzip2, or any standard compression.

Your task is to build an end-to-end pipeline that produces `/app/results.json` -- a JSON object keyed by uppercase problem name (e.g. `"AFIRO"`). For each of the eight problems, independently solve both the primal LP and its corresponding dual LP, and verify the optimality conditions that relate them. Each entry must contain:

- `optimal_value` (number): primal optimal (minimum) objective value
- `dual_optimal_value` (number): optimal value of the dual LP, solved as an independent optimization problem (not extracted from solver internals)
- `duality_gap` (number): |primal_optimal - dual_optimal|
- `cs_max_violation` (number): maximum complementary slackness violation across all primal-dual variable pairs
- `num_rows` (integer): total rows in MPS file including objective row
- `num_cols` (integer): number of structural columns
- `num_nonzeros` (integer): total nonzero coefficients including objective row
- `has_bounds` (boolean): whether the expanded MPS contains a BOUNDS section
- `has_ranges` (boolean): whether the expanded MPS contains a RANGES section

The eight problems are: AFIRO, SC50A, ADLITTLE, SHARE2B, KB2, BORE3D, BOEING2, CAPRI.

All problems are minimization. Optimal values must match published Netlib reference values (from MINOS 5.3 on VAX) within 1e-6 relative tolerance. Duality gaps and complementary slackness violations must be below 1e-4. Problem dimensions must exactly match the Netlib PROBLEM SUMMARY TABLE (rows include cost row; columns and nonzeros exclude slacks but include cost row).