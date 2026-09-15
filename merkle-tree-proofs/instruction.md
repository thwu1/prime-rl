The file `/app/MerkleTree.v` contains a Coq formalization of Merkle hash trees — a cryptographic data structure for authenticated set membership. It axiomatizes a collision-resistant hash function (`hash` with injectivity axiom `hash_inj`), defines binary Merkle trees, authentication paths, proof generation, verification, and leaf update operations.

Five theorems are stated but unproved (marked `Admitted`). Complete all five proofs so the file compiles cleanly and contains no `Admitted` or `admit`.

## Required Theorems

- `completeness`: Authentication paths from `gen_proof` verify against the tree's root hash via `verify`.
- `binding`: An authentication path cannot verify two distinct leaf values against the same root (position-binding security under collision resistance).
- `gen_proof_extracts_leaf`: `gen_proof` returns the value actually stored at the queried leaf index (consistent with `get_leaf`).
- `update_soundness`: After `set_leaf` modifies one leaf, the authentication path from the original tree verifies the new value against the updated root.
- `gen_proof_path_length`: The authentication path length equals the leaf's depth in the tree (consistent with `leaf_depth`).

## Constraints

- Do not modify definitions, type signatures, or axioms — only replace `Admitted.` with proofs.
- Do not introduce additional `Axiom`, `Parameter`, or `Admitted` declarations.
- Helper lemmas may be added anywhere in the file.
- The file must compile: `cd /app && coqc MerkleTree.v`

## Verification

Success requires all of:
1. `coqc MerkleTree.v` exits with code 0
2. No occurrences of `Admitted` or `admit` in the file
3. All five theorem names present with original signatures
4. No axioms beyond `hash_inj`
