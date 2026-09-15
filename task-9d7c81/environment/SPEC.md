# Mutation Analysis Specification

## Target

- Source: `/app/src/algorithms.py`
- Tests: `/app/tests/test_algorithms.py`

## Mutation Operators

Apply the following three operators to **every** function in the source
file.

### AOR — Arithmetic Operator Replacement

Replace each binary arithmetic operator with its designated alternative:

| Original | Replacement |
|----------|-------------|
| `+`      | `-`         |
| `-`      | `+`         |
| `*`      | `//`        |
| `//`     | `*`         |
| `%`      | `*`         |

Each occurrence produces exactly **one** mutant (the single replacement
listed).

### ROR — Relational Operator Replacement

Replace each comparison operator with the alternatives below. Each row
produces one mutant **per replacement** (so `<` yields two mutants).

| Original | Replacements   |
|----------|----------------|
| `<`      | `<=` and `>`   |
| `<=`     | `<`  and `>=`  |
| `>`      | `>=` and `<`   |
| `>=`     | `>`  and `<=`  |
| `==`     | `!=`           |
| `!=`     | `==`           |

### CRP — Constant Replacement (integers only)

Replace integer literal constants. Do **not** mutate boolean literals
(`True`/`False`).

| Original value | Replacement |
|----------------|-------------|
| `0`            | `1`         |
| `1`            | `0`         |
| any other `c`  | `c + 1`     |

Each occurrence produces exactly **one** mutant.

## Analysis Definitions

**Kill matrix.** For each mutant, record which tests detect (kill) it.
A test kills a mutant if the test fails or errors when executed against
the mutated code. The matrix maps each mutant ID to a dict of
test ID → 0 | 1.

**Kill set.** For mutant M: `kill_set(M) = { T : test T kills M }`.

**Subsumption.** Mutant M1 *subsumes* M2 iff `kill_set(M1) ⊊ kill_set(M2)`
(proper subset). M1 is harder to kill — every test that kills M1 also
kills M2, but some tests kill M2 without killing M1.

**Minimal subsuming set.** The set of killable mutants not subsumed by any
other killable mutant.

**Reduced subsumption relations (Hasse diagram).** The transitive reduction
of the subsumption partial order. A relation [M1, M2] (where
`kill_set(M1) ⊊ kill_set(M2)`) appears in the reduced set only if there
is no intermediate killable mutant M3 with
`kill_set(M1) ⊊ kill_set(M3) ⊊ kill_set(M2)`.

**Subsuming mutation score.**
`|minimal_subsuming_set| / total_mutants`, rounded to 4 decimal places.

**Dynamic equivalence.** Killable mutants M1 and M2 are *dynamically
equivalent* iff `kill_set(M1) = kill_set(M2)` (identical, non-empty).

**Minimal test set.** An irredundant subset of tests that collectively
kills every killable mutant (removing any single test leaves at least
one mutant uncovered). Construct by iteratively selecting the test
killing the most yet-uncovered mutants; break ties alphabetically by
test ID.

## Output Format

Write `/app/analysis_report.json` with the following schema:

```json
{
  "summary": {
    "total_mutants": "<int>",
    "killed": "<int>",
    "survived": "<int>",
    "mutation_score": "<float, killed / total_mutants, rounded to 4 decimals>"
  },
  "kill_matrix": {
    "<mutant_id>": { "<test_id>": 0 | 1, "..." : "..." }
  },
  "subsumption": {
    "relations": [ ["<M_sub>", "<M_sup>"], "..." ],
    "reduced_relations": [ ["<M_sub>", "<M_sup>"], "..." ],
    "minimal_subsuming_set": [ "<mutant_id>", "..." ],
    "subsuming_mutation_score": "<float>"
  },
  "dynamic_equivalences": [ ["<m1>", "<m2>"], "..." ],
  "minimal_test_set": [ "<test_id>", "..." ],
  "operator_stats": {
    "AOR": { "count": "<int>", "killed": "<int>", "survived": "<int>", "score": "<float>" },
    "ROR": { "..." : "..." },
    "CRP": { "..." : "..." }
  },
  "mutants": [
    {
      "id": "<e.g. M001>",
      "operator": "<AOR|ROR|CRP>",
      "function": "<function name>",
      "line": "<int>",
      "original": "<original token>",
      "replacement": "<replacement token>",
      "status": "<killed|survived>",
      "killed_by": [ "<test_id>", "..." ]
    }
  ]
}
```

Test IDs must use the form returned by `pytest --collect-only -q`, e.g.
`tests/test_algorithms.py::test_bsearch_found_middle`.
