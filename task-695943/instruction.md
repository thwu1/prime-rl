A compiled shared library at `/app/libcipher.so` implements a custom substitution cipher. The library exports multiple data symbols (256-byte lookup tables) — no source code is provided. Cipher configuration metadata, including which of the library's exported symbols is the target S-box for analysis, is stored in a SQLite database at `/app/cipher.db`.

The target 8-bit S-box (a permutation of {0,...,255}) was constructed as `S(x) = A(f(B(x)))` where:

- **A** and **B** are invertible 8×8 matrices over GF(2), applied as linear maps on 8-bit vectors (bit 0 = LSB). Convert the integer to an 8-bit vector with bit 0 as the least significant bit, multiply by the matrix over GF(2), and convert back.
- **f(y) = (a · y + b) mod 256**, where `a` is an odd integer in [1, 255] and `b` is an integer in [0, 255].

Query the database to identify the target S-box symbol, extract its 256-byte lookup table from the compiled binary, recover the affine-arithmetic decomposition, and write your answer to `/app/answer.json`:

```json
{
  "a": <int>,
  "b": <int>,
  "A": [[a00,...,a07], ..., [a70,...,a77]],
  "B": [[b00,...,b07], ..., [b70,...,b77]]
}
```

where `A[i][j]` and `B[i][j]` are 0 or 1, and the decomposition must satisfy `S[x] = apply_A(f(apply_B(x)))` for all x in {0,...,255}. The matrix-vector product computes output bit `i` as `XOR_j (M[i][j] AND v[j])`.