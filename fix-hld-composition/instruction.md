The C++ program at `/app/main.cpp` defines a tree path query engine for composing non-commutative affine functions f(x) = ax + b (mod 998244353) along tree paths. It supports three operations: point updates, directional path composition evaluation, and path composition inversion (finding a preimage under the composed map via modular inverse). The tree structure with HLD decomposition, the `Affine` type, modular arithmetic utilities, input parsing, and operation dispatch are all fully implemented.

The segment tree core (`build`, `update`, `query_fwd`, `query_rev`) and the `query_path` function are stubs returning identity values. Implement them so the program produces correct output for all test cases in `/app/tests/`.

Key challenges:

- **Non-commutativity**: composing f then g differs from g then f. The segment tree must maintain both a forward composition (left-to-right in position order) and a reverse composition (right-to-left) so that path queries can retrieve the correctly-ordered result regardless of traversal direction.
- **HLD path decomposition**: the path from u to v passes through the LCA. On the u-side, traversal goes from deeper positions to shallower ones (requiring the reverse-ordered composition). On the v-side, traversal goes from shallower to deeper (requiring forward-ordered composition). Segments collected on the v-side must be processed in the correct sequence.
- **Inverse queries** (type 3) are already handled in `main()` — they depend on `query_path` returning a correct composed function.

Compile with `make` in `/app/`. Each `input{k}.txt` in `/app/tests/` has a corresponding `expected{k}.txt`. Test 2 is specifically designed to verify non-commutativity: path u->v and v->u yield different results on the same endpoints. Test 3 includes point updates that zero out the a-coefficient, testing the inversion edge case.