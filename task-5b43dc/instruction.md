The SuiteSparse C library suite is installed (`libsuitesparse-dev`). Headers are under `/usr/include/suitesparse/` and shared libraries are at system linker paths. Three symmetric positive definite sparse matrices in Matrix Market coordinate format are in `/app/matrices/`.

Perform symbolic Cholesky factorization analysis on each matrix under three elimination orderings and produce `/app/results.json`. You may use the SuiteSparse C API, implement the algorithms yourself, or combine approaches.

Evaluate per matrix:
- **Natural** ordering (identity permutation)
- **AMD** ordering (approximate minimum degree)
- **RCM** ordering (Reverse Cuthill-McKee)

Report for each ordering:
- `ordering`: 0-indexed permutation vector of length n, `ordering[new_index] = old_index` (omit for natural)
- `nnz_L`: total nonzeros in L including diagonal
- `etree_height`: elimination tree height (number of levels)
- `flop_count`: Σ_j c_j(c_j + 1) where c_j = subdiagonal nonzeros in column j of L

Per matrix also report: `n` (dimension), `nnz_lower_A` (stored lower-triangle entries including diagonal), `num_components` (connected components), `best_ordering` (which of `"natural"`, `"amd"`, `"rcm"` achieves smallest `nnz_L`).

Output `/app/results.json`:
```json
{
  "<matrix_name>": {
    "n": 25, "nnz_lower_A": 49, "num_components": 1,
    "natural": {"nnz_L": 325, "etree_height": 25, "flop_count": 5200},
    "amd": {"ordering": [...], "nnz_L": ..., "etree_height": ..., "flop_count": ...},
    "rcm": {"ordering": [...], "nnz_L": ..., "etree_height": ..., "flop_count": ...},
    "best_ordering": "amd"
  }
}
```