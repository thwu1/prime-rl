The file `/app/AIG.v` contains a partial Coq formalization of And-Inverter Graphs (AIGs) with complement edges. AIGs are the standard representation for combinational Boolean circuits in logic synthesis: each internal node is an AND gate whose inputs can be optionally inverted via complement-edge flags.

The file defines an AIG datatype, an evaluation semantics, a notion of functional equivalence, and several semantics-preserving transformations (constant folding, complement elimination, identity elimination) composed into an optimization pipeline. Ten theorem statements assert correctness of these transformations, but all proofs are currently `Admitted`.

**Your task:** make `/app/AIG.v` compile successfully under `coqc` with every `Admitted` replaced by a complete proof. Specifically:

1. Complete all ten `Admitted` proofs so that they close with `Qed.` (or `Defined.`).
2. At least one transformation function contains a semantic bug that will prevent its correctness theorem from being provable as-is. Identify and fix the bug.
3. Do not introduce any `Axiom`, `Parameter`, or `Hypothesis` declarations.
4. Do not use the `admit` tactic.
5. Preserve the six `Definition _chk_*` type-checking assertions at the end of the file unchanged.
6. Preserve the canary comment on line 2.

**Success criteria:**

- `coqc /app/AIG.v` exits with code 0.
- The source contains no occurrences of `Admitted.`.
- All required theorem names (`negate_correct`, `negate_involutive`, `const_fold_correct`, `complement_elim_correct`, `identity_elim_correct`, `optimize_correct`) and definitions (`negate`, `const_fold`, `complement_elim`, `identity_elim`, `optimize`) remain present with their original type signatures enforced by the `_chk_*` assertions.
