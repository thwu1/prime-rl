A proprietary cipher's substitution layer is compiled into `/app/cipher.so` (stripped ELF shared library). An analyst's partial cryptanalytic investigation is stored in `/app/analysis.db` (SQLite), with supplementary notes at `/app/notes.txt`.

The S-box is an 8-bit permutation known to decompose as **S = A ∘ X ∘ B** where A and B are invertible affine maps over GF(2)^8 and X is a nonlinear permutation with **triangular** structure: for every k in {1,...,8}, `X(x) mod 2^k` depends only on `x mod 2^k`. The analyst has documented partial algebraic degree analysis and construction details in the database but has not completed the decomposition. Extract the S-box from the binary, confirm the triangular structure, and produce a valid decomposition.

Write your result to `/app/answer.json`:

```json
{
  "A_mat": [[...], ...],
  "A_const": [...],
  "B_mat": [[...], ...],
  "B_const": [...],
  "X_table": [...]
}
```

All fields are required. Constraints:

- `A_mat`, `B_mat`: 8×8 binary matrices (list of 8 rows, each row a list of 8 values, each value in {0,1}), row-major. Both must be invertible over GF(2) (i.e., have determinant 1 mod 2).
- `A_const`, `B_const`: 8-element binary vectors (each element in {0,1}), MSB-first (index 0 is bit 7).
- `X_table`: 256-element integer list where `X_table[i] = X(i)`. Must be a permutation of {0,...,255}. Must be **triangular**: for every k in {1,...,8} and every pair x, y with `x mod 2^k == y mod 2^k`, it must hold that `X(x) mod 2^k == X(y) mod 2^k`.

Affine maps operate over GF(2): `A(v) = A_mat * v XOR A_const`, and similarly for B. The composition `A(X(B(x)))` must equal `S(x)` for all x in {0,...,255}.