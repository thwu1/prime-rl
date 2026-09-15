The file `/app/MultiLimbArith.v` defines a multi-limb integer arithmetic library in Coq with three modules: `Assoc` (associational representation as weight-digit pairs), `Pos` (positional representation with a parametric weight function), and `UWeight` (uniform base-2^w weight functions).

Seven lemmas are currently stub-proved with `Admitted` and must be replaced with complete proofs so that `coqc /app/MultiLimbArith.v` succeeds with exit code 0. The lemmas are:

1. `Assoc.eval_split` -- splitting an associational list by weight divisibility preserves evaluation: `eval (fst (split s p)) + s * eval (snd (split s p)) = eval p`
2. `Assoc.eval_reduce` -- modular reduction preserves value mod `(s - eval c)`
3. `Pos.eval_partition` -- partitioning an integer into positional digits correctly decomposes it: `eval n (partition_val n x) = x mod weight n`
4. `Pos.partition_bounded` -- each partition digit `d_i` satisfies `0 <= d_i < weight(i+1)/weight(i)`
5. `UWeight.uweight_divides` -- `uweight lgr i` divides `uweight lgr (S i)`
6. `UWeight.uweight_sum` -- `uweight lgr (i + j) = uweight lgr i * uweight lgr j`
7. `UWeight.uweight_mod_mod` -- nested modular reduction: `(x mod uweight lgr n) mod uweight lgr m = x mod uweight lgr m` when `m <= n`

Replace each `Admitted` with a complete proof ending in `Qed`. Do not change any `Definition`, `Fixpoint`, type signature, `Module`/`Section` boundary, or hypothesis. Do not add axioms or use the `admit` tactic. You may add helper lemmas outside the modules if needed.

**Output:** Write the completed file to `/app/MultiLimbArith.v`.

**Success criterion:** `coqc /app/MultiLimbArith.v` exits with code 0 and produces `/app/MultiLimbArith.vo`.
