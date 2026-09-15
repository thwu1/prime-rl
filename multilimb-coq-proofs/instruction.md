The file `/app/MultiLimbArith.v` contains a self-contained Coq library for multi-limb modular arithmetic with associational and positional integer representations, carry propagation, partitioning, addition, and a uniform-weight system.

Twelve lemmas are currently `Admitted` (stubs without proofs). Replace every `Admitted` with a valid proof so that `/app/MultiLimbArith.v` compiles cleanly under `coqc` with exit code 0 and no errors.

The admitted lemmas, grouped by module:

**Assoc** (associational representation — list of (weight, value) pairs):
1. `eval_mul` — multiplication distributes: eval(mul p q) = eval p * eval q
2. `eval_negate_snd` — negation correctness: eval(negate_snd p) = - eval p
3. `eval_map_scale` — uniform scaling: eval(map (a*w, x*v) p) = a*x*eval p
4. `eval_carry` — carry preserves evaluation
5. `eval_rev` — evaluation is order-independent: eval(rev p) = eval p

**Pos** (positional representation — implicit weights via weight function):
6. `eval_snoc` — evaluation of snoc'd element
7. `eval_part` — partition evaluation: eval n (part n x) = x mod weight n
8. `eval_add_lists` — element-wise addition preserves positional semantics

**UWeight** (uniform radix-2^w weight system):
9. `uweight_0` — weight at index 0 is 1
10. `uweight_S` — uweight lgr (S i) = 2^lgr * uweight lgr i
11. `uweight_mul` — successive weights satisfy divisibility
12. `uweight_sum` — uweight lgr (i+j) = uweight lgr i * uweight lgr j

Compile with:
```
coqc -Q /app "" /app/MultiLimbArith.v
```

The file must produce exit code 0, contain zero occurrences of the keyword `Admitted`, and retain all original definitions, type signatures, module structure, and lemma statements unchanged. You may add new helper lemmas.
