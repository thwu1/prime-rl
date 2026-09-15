A partial Coq formalization of a simply-typed lambda calculus with pairs, unit, and a subtyping relation (with `Top`) is provided at `/app/stlc_sub/`. The project contains five files compiled via `make`:

- `Types.v` — type syntax: `Top`, `Arrow`, `Prod`, `Unit`
- `Subtyping.v` — declarative subtyping rules (without `S_Trans`) and admitted lemmas for transitivity and inversion
- `Terms.v` — term syntax, values, substitution, small-step semantics
- `Typing.v` — declarative typing with subsumption (`T_Sub`), admitted canonical-forms lemmas, progress and preservation theorems, a typing inversion lemma for abstractions, and a substitution lemma
- `Algorithmic.v` — mutually recursive `sub_dec`/`sub_dec_rev` functions for deciding subtyping (with admitted soundness/completeness proofs) and a placeholder `typecheck` function to implement

Running `make` in `/app/stlc_sub/` currently fails due to admitted proofs and the missing `typecheck` implementation.

Fill in every `(* FILL IN HERE *)` hole and replace every `Admitted.` with a complete proof so that `make` succeeds with zero errors in `/app/stlc_sub/`. The `typecheck` function must be a structurally recursive `Fixpoint` returning `option ty` that computes principal types. You may introduce additional helper lemmas (e.g., typing inversion lemmas for other term forms, or properties relating `sub_dec` and `sub_dec_rev`) as needed.

Do not alter any existing definitions, inductive types, theorem statements, or the `_CoqProject`/`Makefile`. Only fill holes, replace `Admitted.`, and add new helper lemmas.