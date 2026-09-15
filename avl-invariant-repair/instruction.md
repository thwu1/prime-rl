The file `/app/avl.py` implements an ordered set data structure using AVL trees, based on the Isabelle/AFP (Archive of Formal Proofs) formalization. Beyond basic insert/delete operations, it includes `split` and `join` primitives and set-theoretic operations (`union`, `intersection`, `difference`) built on them.

The implementation has multiple bugs across its layers — from core tree rotations through the split/join infrastructure to the set operations themselves — and one function that was left unimplemented. The Isabelle/HOL formal specification at `/app/reference_spec.thy` defines the correct semantics and invariants for all operations.

Fix all bugs and complete the missing implementation in `/app/avl.py` so that every operation maintains the `avl` balance invariant, the `is_ord` BST ordering invariant, and correct `set_of` semantics as defined in the specification.

Run `/app/check_invariants.py` to see which operations currently fail.