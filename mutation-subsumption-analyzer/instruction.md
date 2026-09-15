A Python project at `/app/project/` contains source code (`/app/project/src/mathlib.py`) and a test suite (`/app/project/tests/test_mathlib.py`).

Build a mutation testing pipeline that generates first-order mutants using three standard operator families — AOR (Arithmetic Operator Replacement), ROR (Relational Operator Replacement), and LCR (Logical Connector Replacement) — executes each mutant against the project's test suite, and performs subsumption analysis to identify dominator mutants.

## Output

Write results to `/app/results/` as four JSON files described below.

### `mutants.json`

Array of objects, each with fields: `id` (string), `operator` (one of `"AOR"`, `"ROR"`, `"LCR"`), `function` (name of containing function), `line` (int), `original` (original operator symbol), `replacement` (replacement operator symbol), `status` (one of `"killed"`, `"survived"`, `"equivalent"`, `"timeout"`).

### `kill_matrix.json`

Object with fields: `mutant_ids` (array of mutant id strings), `test_names` (array of test function name strings), `matrix` (2D array of integers where `matrix[i][j]` is `1` if test `j` kills mutant `i`, else `0` — values must be exactly `0` or `1`). The number of rows must equal `len(mutant_ids)` and each row length must equal `len(test_names)`.

### `subsumption.json`

Object with fields: `subsuming_mutant_ids` (array of dominator mutant ids), `subsumption_edges` (array of `[a, b]` pairs). An edge `[a, b]` means mutant `a` strictly subsumes mutant `b`: the kill set of `a` must be a proper subset of the kill set of `b` (i.e., every test that kills `a` also kills `b`, but `b` is killed by at least one additional test). The `subsuming_mutant_ids` set must be exactly the set of killable mutants that are not strictly subsumed by any other killable mutant (dominator mutants).

### `metrics.json`

Object with these required fields:
- `total_mutants`: total number of generated mutants (must be >= 40)
- `killed`: count of killed mutants
- `survived`: count of survived mutants
- `equivalent`: count of equivalent mutants (default 0)
- `mutation_score`: killed / (total - equivalent), must be in [0, 1] and >= 0.5
- `operators`: object with keys `"AOR"`, `"ROR"`, `"LCR"`, each containing `{generated, killed}` where `generated` > 0 and `killed` <= `generated`
- `subsuming_mutants_total`: number of dominator mutants (must be > 0 and < `total_mutants`)
- `subsuming_mutants_killed`: killed dominators count
- `subsuming_mutation_score`: killed dominators / total dominators, in [0, 1]

## Consistency constraints

- `killed + survived + equivalent + timeout = total_mutants` (where `equivalent` and `timeout` default to 0 if absent)
- The number of mutants with at least one `1` in their kill matrix row must equal `killed` in metrics
- `subsuming_mutants_total < total_mutants` (the dominator set is always a proper subset)