Implement a verified optimizing pass for the DAG-based computation graph framework at `/app/`.

The directory contains a DAG IR for 32-bit unsigned arithmetic (`/app/dag_ir.py`), a pattern-matching rewrite engine (`/app/pattern.py`), eight test programs with redundancies (`/app/programs.py`), and six candidate rewrite rules of unknown soundness (`/app/candidate_rules.py`).

Produce two artifacts:

**`/app/optimizer.py`** — Export `optimize(dag: DAG) -> DAG` that rewrites each program's DAG to meet the computational-node-count targets below while preserving input–output equivalence for all uint32 inputs. The `range_fold` program contains comparisons whose truth depends on value ranges propagating through arithmetic — pattern matching on syntactic structure alone cannot resolve them. The `algebraic_factor` program contains multiplicative redundancies that require algebraic restructuring and awareness of power-of-two representations. The `verified_rewrites` program requires incorporating only provably sound candidate rules from `/app/candidate_rules.py`; unsound rules must not be applied.

| Program | Target |
|---|---|
| identity_cleanup | ≤ 11 |
| const_propagation | ≤ 4 |
| cancel_annihilate | ≤ 2 |
| cond_collapse | ≤ 5 |
| range_fold | ≤ 3 |
| algebraic_factor | ≤ 3 |
| multi_pass_compose | ≤ 2 |
| verified_rewrites | ≤ 2 |

**`/app/verification_report.json`** — Formally verify each of the six candidate rules in `/app/candidate_rules.py` over 32-bit bitvectors using the Z3 SMT solver (`z3-solver` on PyPI). For each rule, determine whether it is universally sound or has a counterexample demonstrating unsoundness. Attention to unsigned overflow, shift truncation, and modular arithmetic edge cases is essential. Format:

```json
{"C1": {"verdict": "sound"}, "C2": {"verdict": "unsound", "counterexample": {"x": 123, "c": 4}}}
```

Counterexamples must include concrete uint32 values for every free variable that make the LHS evaluate differently from the RHS.