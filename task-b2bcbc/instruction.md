The Python project at `/app/` implements half-open interval `[start, end)` arithmetic, scheduling algorithms, and constraint-based resource allocation across three modules:

- `/app/intervallib/intervals.py` — interval overlap, merge, complement, coverage, intersection, symmetric difference
- `/app/intervallib/scheduling.py` — weighted job scheduling, earliest-deadline-first, critical path analysis
- `/app/intervallib/solver.py` — precedence constraint propagation over interval domains, resource load profiling, capacity-constrained scheduling

The test suite at `/app/tests/` achieves line coverage but is known to be mutation-weak. A mutation analysis report at `/app/mutations.json` catalogs 15 AST-level mutations across these modules — comparison boundary swaps, arithmetic operator replacements, and augmented-assignment weakenings. Each mutation is a single-token semantic change.

`mutmut` (v3.5.0) is pre-installed in the environment and configured in `/app/pyproject.toml`. Use `mutmut` to validate your mutation kills: `mutmut run` performs mutation testing against the test suite, `mutmut results` lists mutant statuses, and `mutmut show <mutant_name>` displays the diff for individual mutants. Note that `mutmut` generates mutations beyond the 15 cataloged in `mutations.json` — focus your analysis and reporting on those 15 mutations.

Analyze every mutation in the catalog and determine whether it is **killable** (there exists an input that distinguishes the mutated code from the original) or **equivalent** (the mutated code produces identical output for all possible inputs — a formal property requiring proof, not merely "hard to test").

For each killable mutation: add tests to `/app/tests/` that pass on the original code but fail when the mutation is applied.

For each equivalent mutation: annotate the affected source line with `# pragma: no mutate` and a comment justifying why the mutation is semantically equivalent.

Do not modify library source files except to add `# pragma: no mutate` annotations on lines with genuinely equivalent mutations.

Generate a line-coverage report at `/app/coverage.json` using the `coverage` tool (`coverage run` followed by `coverage json`).

Write a final analysis report to `/app/mutation_analysis.json` containing: `total_mutants` (int, 15), `killed` (int), `survived` (int), `equivalent` (int), `mutation_score` (float: killed / (total_mutants - equivalent)).