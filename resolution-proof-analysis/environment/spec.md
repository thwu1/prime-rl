# Resolution Proof Analysis Tool — Specification

## Overview

Implement a tool that analyzes propositional resolution proofs. For each instance in `/app/instances/`, read the CNF formula and its associated resolution proof, then validate the proof, compute complexity metrics, perform proof trimming, and check regularity. Write all results to `/app/results.json`.

## Input Formats

### DIMACS CNF (`.cnf`)

- Lines starting with `c` are comments.
- Header: `p cnf <num_vars> <num_clauses>`
- Each clause is a line of space-separated integer literals terminated by `0`.
- Positive literal `k` means variable k is true; `-k` means variable k is false.

### Resolution Proof (`.res`)

- Lines starting with `c` are comments.
- Header: `p proof <num_steps>`
- Each step: `<step_id> <lit1> <lit2> ... 0 <ant1> <ant2> 0`
  - `step_id`: positive integer, unique.
  - Literals before the first `0`: the clause derived at this step (empty for the empty clause).
  - After the first `0`, before the final `0`: antecedent step IDs.
  - **Input clause**: no antecedents (format: `<id> <lits...> 0 0`).
  - **Resolution step**: exactly two antecedents (format: `<id> <lits...> 0 <ant1> <ant2> 0`).

## Analysis Tasks

### 1. Proof Validation

Process steps in file order. For each step, verify:

- **Input clauses** (no antecedents): the clause must appear in the CNF formula (as a set of literals). If not, error type is `phantom_clause`.
- **Resolution steps** (two antecedents): both antecedent IDs must reference previously defined steps. If not, error type is `invalid_reference`. The claimed clause must be a valid resolvent of the two antecedent clauses. If not, error type is `invalid_resolvent`.

**Resolution rule**: clauses C1 and C2 can be resolved on variable v if literal l is in C1 and literal -l is in C2 (where |l| = v). The resolvent is (C1 \ {l}) union (C2 \ {-l}). A resolution step is valid if there exists some variable v such that the claimed clause equals the resolvent on v.

Report the **first** erroneous step (by file order) and its error type. If the proof is valid, proceed to metrics.

### 2. Proof Metrics

For valid proofs, compute:
- `total_steps`: total number of steps (inputs + derived).
- `input_steps`: number of input clause steps.
- `derived_steps`: number of resolution steps.
- `proof_depth`: the maximum depth across all steps. Input clauses have depth 0. A resolution step has depth = 1 + max(depth(ant1), depth(ant2)).

### 3. Proof Trimming

Find the **first** step (by file order) that derives the empty clause (a step with zero literals). Compute the minimal sub-derivation: the smallest set of steps needed to derive that empty clause, found by backward reachability through the antecedent graph.

Report:
- `trimmed_total_steps`: number of steps in the minimal sub-derivation.
- `trimmed_derived_steps`: number of resolution steps in it.
- `essential_inputs`: number of input clauses in it.
- `trimmed_proof_depth`: depth of the empty clause within the trimmed sub-derivation.
- `trimmed_step_ids`: sorted list of step IDs in the minimal sub-derivation.

### 4. Regularity Check

A resolution proof is **regular** if on every directed path from any input clause to the empty clause in the proof DAG, each variable is used as a resolution pivot at most once.

The **pivot** of a resolution step is the variable v on which resolution was performed (i.e., the variable whose positive literal appears in one antecedent and negative literal in the other, producing the claimed resolvent).

Check regularity of the **trimmed** proof and report `is_regular` (boolean).

## Output Format

Write `/app/results.json` with this structure:

```
{
  "results": {
    "<instance_name>": { ... },
    ...
  }
}
```

For **valid** proofs:
```
{
  "valid": true,
  "total_steps": <int>,
  "input_steps": <int>,
  "derived_steps": <int>,
  "proof_depth": <int>,
  "trimmed_total_steps": <int>,
  "trimmed_derived_steps": <int>,
  "essential_inputs": <int>,
  "trimmed_proof_depth": <int>,
  "trimmed_step_ids": [<int>, ...],
  "is_regular": <bool>
}
```

For **invalid** proofs:
```
{
  "valid": false,
  "first_error_step": <int>,
  "error_type": "<string>"
}
```

Where `error_type` is one of: `"phantom_clause"`, `"invalid_reference"`, `"invalid_resolvent"`.
