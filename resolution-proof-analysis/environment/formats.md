# Proof Certificate Formats

## Input Formats

### DIMACS CNF (`formula.cnf`)

Standard DIMACS CNF format for propositional formulas in conjunctive normal form.

- Lines starting with `c` are comments
- Problem line: `p cnf <num_vars> <num_clauses>`
- Each subsequent line is a clause: space-separated integer literals terminated by `0`
- Positive integer `k` represents variable k; `-k` represents its negation

### Resolution Proof (`proof.res`)

A resolution proof consists of numbered steps deriving new clauses from existing ones.

- Lines starting with `c` are comments
- Problem line: `p proof <num_steps>`
- Step format: `<step_id> <lit1> ... <litn> 0 <ant1> ... <antm> 0`
  - `step_id`: unique positive integer identifier
  - Literals (before first `0`): the clause at this step (empty for the empty clause)
  - Antecedents (between the two `0` terminators): IDs of premise steps
  - An input clause has zero antecedents: `<id> <lits> 0 0`
  - A derived step has exactly two antecedents: `<id> <lits> 0 <ant1> <ant2> 0`

### Clause Partition (`partition.json`)

Some instances include a `partition.json` file that partitions the input clauses into two sets **A** and **B**. The file has the form:

```json
{"A": [<step_ids...>], "B": [<step_ids...>]}
```

Step IDs reference the input-clause steps in `proof.res`. Every input-clause step must appear in exactly one of A or B. The combined formula A ∧ B is unsatisfiable.

## Resolution Rule

Clauses C₁ and C₂ can be **resolved** on variable v if literal l ∈ C₁ and ¬l ∈ C₂ (where |l| = v). The resolvent is (C₁ \ {l}) ∪ (C₂ \ {¬l}). The variable v is called the **pivot** of the step.

## Output Schema

Write `/app/results.json` with structure:

```json
{
  "results": {
    "<instance_directory_name>": { ... },
    ...
  }
}
```

### Instances with a resolution proof (`.res` file present)

The proof must be checked for correctness, and the formula's satisfiability must be independently verified.

**Valid proof:**
```json
{
  "valid": true,
  "formula_unsatisfiable": bool,
  "total_steps": int,
  "input_steps": int,
  "derived_steps": int,
  "proof_depth": int,
  "proof_width": int,
  "is_tree_like": bool,
  "trimmed_total_steps": int,
  "trimmed_derived_steps": int,
  "essential_inputs": int,
  "trimmed_proof_depth": int,
  "trimmed_step_ids": [int, ...],
  "is_regular": bool
}
```

**Field definitions:**
- `formula_unsatisfiable`: whether the formula is independently confirmed to be unsatisfiable
- `total_steps`, `input_steps`, `derived_steps`: counts of all steps, input-clause steps (zero antecedents), and derived steps (two antecedents)
- `proof_depth`: maximum depth in the proof DAG — input steps have depth 0; a derived step has depth 1 + max(depths of its antecedents)
- `proof_width`: the maximum clause size (number of literals) across all steps in the proof
- `is_tree_like`: whether the proof is tree-like — each derived step is used as an antecedent by at most one other step
- `trimmed_*`: corresponding metrics restricted to the minimal sub-derivation that derives the first empty clause (by file order)
- `essential_inputs`: input-clause steps in the minimal sub-derivation
- `trimmed_step_ids`: sorted list of step IDs in the minimal sub-derivation
- `is_regular`: whether the minimal sub-derivation is regular — no variable serves as resolution pivot more than once along any directed path from an input clause to the empty clause

**Invalid proof:**
```json
{
  "valid": false,
  "formula_unsatisfiable": bool,
  "first_error_step": int,
  "error_type": "phantom_clause" | "invalid_reference" | "invalid_resolvent"
}
```

Error types:
- `phantom_clause`: an input-clause step claims a clause not present in the formula
- `invalid_reference`: a derived step cites an antecedent ID not yet defined
- `invalid_resolvent`: a derived step's clause is not a valid resolvent of its antecedents

Report the first erroneous step by file order.

### Craig Interpolation (instances with `partition.json`)

When a valid proof instance also contains a `partition.json` file, compute a **Craig interpolant** from the resolution proof and the given partition.

**Background.** Given disjoint clause sets A and B whose conjunction is unsatisfiable, the Craig interpolation theorem guarantees the existence of a propositional formula I (the interpolant) satisfying three properties:

1. **A-implication**: every satisfying assignment of A, when projected to the shared variables, satisfies I
2. **B-separation**: no satisfying assignment of B, when projected to the shared variables, satisfies I
3. **Variable restriction**: I uses only the shared variables Var(A) ∩ Var(B)

Add these fields to the valid-proof output:

```json
{
  ...,
  "shared_variables": [int, ...],
  "interpolant_models": [[int, ...], ...]
}
```

- `shared_variables`: sorted list of variables that appear in both A-clauses and B-clauses
- `interpolant_models`: the set of all satisfying assignments of the interpolant over the shared variables, represented as a list of assignments. Each assignment is a sorted list of signed integers (positive = true, negative = false) covering every shared variable exactly once. The outer list is sorted lexicographically.

### Instances with only a formula (no `.res` file)

```json
{
  "satisfiable": bool,
  "solution": [int, ...] | null
}
```

- `satisfiable`: whether the formula is satisfiable
- `solution`: a satisfying assignment as a list of signed literals (positive = true, negative = false) if satisfiable; `null` otherwise
