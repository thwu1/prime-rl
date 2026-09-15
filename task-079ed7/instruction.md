`/app/instances/` contains weighted partial MaxSAT benchmark instances in WCNF format. Some use the post-2022 new format (hard clauses prefixed with `h`, soft clauses prefixed by integer weight, clauses terminated by `0`, comment lines start with `c`). Others use the legacy format with a header `p wcnf <nvars> <nclauses> <top>` where clauses with weight >= top are hard and those with weight < top are soft. Instances range from 3 to 35 variables and include edge cases from the MaxSAT Evaluation regression suite: empty hard clauses, 0-weight soft clauses, integer weights up to 2^63, and contradictory hard clauses.

`/app/outputs/` contains solver output files in MSE competition format, some with bugs. Each output file has a `c` comment line identifying the instance it was run against.

`/app/tools/wcnf2dimacs.py` is a provided WCNF-to-DIMACS CNF converter. It has bugs — it fails on legacy-format WCNF inputs and its `-hards` flag does not correctly extract hard clauses from legacy files.

The SAT solver `minisat` is installed at `/usr/bin/minisat`. It accepts DIMACS CNF format, writes SAT/UNSAT status and variable assignments to a result file, and returns exit code 10 (SAT) or 20 (UNSAT).

## Deliverables

**`/app/maxsat_solver`** — Executable that solves weighted partial MaxSAT instances optimally. Invocation: `/app/maxsat_solver <wcnf_file>`. Must use `minisat` as the SAT backend for satisfiability queries — direct enumeration of all 2^n variable assignments is not permitted. Must auto-detect WCNF format (new h-line or legacy p-line). Output in MSE competition format: `o <cost>` line, `s OPTIMUM FOUND` or `s UNSATISFIABLE` status line, and `v <space-separated 0/1 assignment>` line where the i-th value corresponds to variable i. Exit code 30 for OPTIMUM FOUND, 20 for UNSATISFIABLE. Must correctly handle empty hard clauses (always unsatisfiable), 0-weight soft clauses, weights up to 2^63, and genuinely unsatisfiable instances.

**`/app/tools/wcnf2dimacs_fixed.py`** — Corrected WCNF-to-DIMACS converter. Invocation: `python3 /app/tools/wcnf2dimacs_fixed.py [-hards] <wcnf_file>`. Outputs valid DIMACS CNF to stdout. Must auto-detect and correctly handle both WCNF format variants. With `-hards`, extracts only hard clauses.

**`/app/bug_report.json`** — JSON object mapping each filename in `/app/outputs/` to `{"valid": bool, "bugs": [<strings>]}`. Bug type strings: `"cost_mismatch"` when the `o`-line cost does not match the actual cost of the truth assignment, `"hard_clause_violation"` when the assignment violates a hard clause, `"false_unsatisfiable"` when the solver claims UNSATISFIABLE but the instance is feasible. Verification of UNSAT claims must use `minisat` rather than brute-force enumeration.