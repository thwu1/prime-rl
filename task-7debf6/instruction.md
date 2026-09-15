A Python numerical library is at `/app/target/mathlib.py` with a partial test suite at `/app/tests/test_basic.py`. Pre-generated first-order mutants (`M001.py` through `M034.py`) and their manifest are in `/app/mutants/`. The output schema is in `/app/spec.json`.

Produce:

## 1. `/app/output/results.json`

A JSON object with the following required fields:

- `total_mutants` (int): must equal 34 (the manifest count).
- `killed` (int): mutants detected by the test suite.
- `survived` (int): mutants not detected. Must satisfy `killed + survived == total_mutants`.
- `equivalent` (int): survived mutants classified as semantically equivalent to the original.
- `mutation_score` (float): `killed / (total_mutants - equivalent)`.
- `operator_counts` (object): maps each of the five operator types — `AOR`, `ROR`, `LCR`, `AOD`, `UOI` — to an int count. Counts must sum to `total_mutants`.
- `kill_matrix` (object): maps each killed mutant ID (e.g. `"M002"`) to a non-empty list of test function name strings that killed it. Must have exactly `killed` entries; survived/equivalent mutants must not appear.
- `equivalent_mutants` (list of objects): each with `"id"` (str) and `"reason"` (str, >10 chars justifying equivalence). The known equivalent mutants **M001**, **M005**, and **M007** must all be classified as equivalent.
- `surviving_non_equivalent` (list of str): IDs of survived mutants classified as non-equivalent. Must satisfy `equivalent + len(surviving_non_equivalent) == survived`.
- `subsuming_mutants` (list of str): IDs of dynamically subsuming killed mutants — those whose kill set is not a proper superset of any other killed mutant's kill set. Must be non-empty and a subset of killed mutants. No subsuming mutant's kill set may be a proper superset of any other killed mutant's kill set.
- `subsuming_mutation_score` (float): must be in [0, 1].
- `branch_coverage_original` (float): branch coverage percentage (0–100] of `test_basic.py` alone against `mathlib.py`.
- `branch_coverage_enhanced` (float): branch coverage percentage (0–100] of both test files combined. Must be >= `branch_coverage_original`.

At least 25 mutants must be killed.

## 2. `/app/tests/test_enhanced.py`

Additional pytest tests that:

- Pass on the unmutated `mathlib.py`.
- Detect mutation **M011** (`is_sorted`: `>` changed to `>=` on line 28) — requires testing with duplicate adjacent elements.
- Detect mutation **M020** (`variance`: `< 2` changed to `<= 2` on line 55) — requires calling `variance` with exactly 2 values.
- Detect mutation **M033** (first `and` changed to `or` in the triangle inequality on line 87).
- Detect mutation **M034** (second `and` changed to `or` in the triangle inequality on line 87) — both require testing with sides that violate the triangle inequality.

## 3. `/app/output/subsumption.dot`

Graphviz DOT file representing the transitive reduction of the subsumption partial order among killed mutants. Must contain the `digraph` keyword and at least one directed edge using the format `"Mxxx" -> "Myyy"`. Every edge `M1 -> M2` must satisfy T(M1) ⊂ T(M2) (M1's kill set is a proper subset of M2's kill set) as recorded in the kill matrix.

## 4. `/app/output/subsumption.png`

Rendered PNG of the subsumption DAG (valid PNG file header required). Use the `dot` command from Graphviz, which is pre-installed.