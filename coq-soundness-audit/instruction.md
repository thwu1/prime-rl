Three Coq source files at `/app/` implement a small library:

- `/app/ModLib.v` — Feature flag registry using module functors and aliasing
- `/app/RecLib.v` — Recursive accumulator with depth-controlled computation
- `/app/IterLib.v` — Bounded iteration framework with dependent safety certificates

Each file compiles without errors under the installed `coqc`, yet each contains a soundness vulnerability — a well-typed definition that the kernel should reject but does not. The three vulnerabilities exploit different mechanisms.

Create six self-contained Coq files in `/app/`:

**Exploit files** — each must define `Theorem unsound : False.` followed by `Print Assumptions unsound.`:

- `/app/exploit_mod.v`
- `/app/exploit_rec.v`
- `/app/exploit_iter.v`

Requirements: each compiles with `coqc` (exit 0) and `Print Assumptions unsound` outputs "Closed under the global context" (no axioms used).

**Fixed replacement files** preserving the library API without the vulnerability:

`/app/fixed_mod.v` must export definitions `a_current`, `b_current`, `a_flipped`, `b_flipped`, each of type `bool`. The following must hold by `reflexivity`: `a_current = true`, `b_current = false`, `a_flipped = false`, `b_flipped = true`. The equality `a_current = b_current` must NOT be provable by `reflexivity`.

`/app/fixed_rec.v` must export `deep_acc : nat -> nat -> (nat -> nat) -> nat` and `shallow_run : nat -> nat`. The equality `shallow_run 5 = 7` must hold by `reflexivity`. The step equation `deep_acc (S d) l f = deep_acc d (S l) (fun x => deep_acc x 0 f)` must NOT hold by `reflexivity`.

`/app/fixed_iter.v` must export `bounded_result : nat`. The equality `bounded_result = 10` must hold by `reflexivity`. The definition `safety_check` must either be absent or not derivable as a proof of `False`.

All six files must be self-contained — no `Require Import` of other `/app/` files. Standard library imports are permitted. All must compile with `coqc`.
