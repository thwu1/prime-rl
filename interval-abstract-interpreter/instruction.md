Implement a static analyzer at `/app/analyzer.py` for a simple imperative language using the interval abstract domain. The analyzer must detect buffer overflows, division-by-zero, and assertion violations in programs specified as JSON ASTs.

The full language specification, domain operation definitions, check semantics, and output format are documented at `/app/spec.md`. Test programs are at `/app/programs/*.json`.

The analyzer must:
- Accept a program JSON file path as its first command-line argument
- Perform abstract interpretation using the interval domain with widening and narrowing for loop fixpoint computation
- Refine abstract states at conditional branches using the branch condition
- Emit checks (boa, dbz, assert) with statuses (safe, warning, error) as defined in the spec
- Output results as JSON to stdout

Programs include non-deterministic inputs, nested conditionals with guard refinement, nested loops requiring proper widening convergence, and cases where narrowing is essential for precision recovery. One program demonstrates a fundamental limitation of the interval domain (inability to capture relational invariants like `i < n` implying `n - i > 0`).