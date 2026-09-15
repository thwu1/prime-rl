A set of five generalized bicycle (GB) quantum error-correcting codes is defined in `/app/codes.json`. Each code is specified by:

- Grid dimensions `l` and `m` defining an `l x m` toroidal qubit layout
- Polynomial terms for matrices `A` and `B`, given as `[y_exponent, x_exponent]` pairs

The construction uses cyclic shift operators `x = kron(Sd(l), Id(m))` and `y = kron(Id(l), Sd(m))`, where `Sd(n)` is the `n x n` cyclic downward shift (row `j` maps to row `(j+1) mod n`). Each matrix `A` (or `B`) is the GF(2) sum of terms `y^a * x^b` for each `[a, b]` in its term list. The CSS parity check matrices are `HX = [A | B]` and `HZ = [B^T | A^T]`, acting on `n = 2*l*m` data qubits.

For each code, compute the full `[[n, k, d]]` parameters:

- `n = 2 * l * m` (number of physical qubits)
- `k = n - rank_GF2(HX) - rank_GF2(HZ)` (number of logical qubits, where rank is computed over GF(2))
- `d` = code distance: the minimum Hamming weight of any non-trivial logical operator, i.e., the minimum weight of vectors in `ker(HX)` that are not in `rowspace(HZ)`, and symmetrically for Z-type, taking the overall minimum

Compute the figure of merit `kd^2/n` for each code. Write results to `/app/results.json` with the following exact structure:

```json
{
  "codes": {
    "<name>": {"n": <int>, "k": <int>, "d": <int>, "kd2_over_n": <float rounded to 4 decimal places>}
  },
  "best_code": "<name of code with highest kd2/n>"
}
```