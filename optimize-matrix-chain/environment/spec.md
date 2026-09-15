# Generalized Matrix Chain Optimization — Specification

## Problem Format

Each problem is a JSON file in `/app/problems/` with:

```json
{
  "id": "problem_1",
  "chain": [
    {"matrix": "A", "transpose": false, "invert": false},
    {"matrix": "D", "transpose": false, "invert": true}
  ],
  "matrices": {
    "A": {"rows": 100, "cols": 100, "properties": ["lower_triangular"]},
    "D": {"rows": 100, "cols": 100, "properties": ["diagonal"]}
  }
}
```

The `chain` defines the expression to evaluate: `T_0 @ T_1 @ ... @ T_{n-1}` where each term
`T_i` is a matrix optionally transposed and/or inverted. All inverted matrices are square.

Matrix properties are exactly one of: `general`, `diagonal`, `lower_triangular`,
`upper_triangular`, `spd` (symmetric positive definite).

## Kernel Catalog

All costs use **integer floor division** (`//`). Variables: `m`, `k`, `n` refer to
the dimensions of the operands as described.

### Multiply Kernels

Compute `C = Left[m,k] @ Right[k,n]`.

| Kernel   | Requirement                                      | Cost        |
|----------|--------------------------------------------------|-------------|
| GEMM     | None                                             | 2·m·k·n     |
| TRMM     | Left is triangular and square (m=k), OR Right is triangular and square (k=n) | m·k·n |
| DIAGMM   | Left is diagonal and square (m=k), OR Right is diagonal and square (k=n)     | m·n   |

### Left-Solve Kernels

Compute `X = inv(A[m,m]) @ B[m,n]` (solving `A·X = B`).

| Kernel     | Requirement on A      | Cost                        |
|------------|-----------------------|-----------------------------|
| GESV       | None                  | (2·m³)//3 + 2·m²·n          |
| TRSM       | triangular            | m²·n                        |
| POSV       | spd                   | m³//3 + 2·m²·n              |
| DIAGSOLVE  | diagonal              | m·n                         |

### Right-Solve Kernels

Compute `X = B[m,n] @ inv(A[n,n])` (solving `X·A = B`).

| Kernel       | Requirement on A      | Cost                        |
|--------------|-----------------------|-----------------------------|
| GESV_R       | None                  | (2·n³)//3 + 2·m·n²          |
| TRSM_R       | triangular            | m·n²                        |
| POSV_R       | spd                   | n³//3 + 2·m·n²              |
| DIAGSOLVE_R  | diagonal              | m·n                         |

### Explicit Inverse Kernels

Compute `inv(A[m,m])`.

| Kernel   | Requirement    | Cost         |
|----------|----------------|--------------|
| GETRI    | None           | 2·m³         |
| TRTRI    | triangular     | m³//3        |
| DIAG_INV | diagonal       | m            |

## Property Propagation

### Multiply: properties of `C = A @ B`

- If both A and B are `diagonal` → `diagonal`
- If both are `lower_triangular` → `lower_triangular`
- If both are `upper_triangular` → `upper_triangular`
- If A is `diagonal` → result inherits B's property
- If B is `diagonal` → result inherits A's property
- Otherwise → `general`

### Transpose: properties of `A^T`

| Original            | Transposed          |
|---------------------|---------------------|
| symmetric           | symmetric           |
| spd                 | spd                 |
| lower_triangular    | upper_triangular    |
| upper_triangular    | lower_triangular    |
| diagonal            | diagonal            |
| general             | general             |

### Inverse: properties of `inv(A)`

All listed properties are preserved under inversion:
`diagonal`, `lower_triangular`, `upper_triangular`, `spd`, `symmetric`, `general`.

## Handling Inversions

When the chain contains an inverted term `inv(A)`, the optimizer may either:

1. **Explicit inverse**: Compute `inv(A)` using an inverse kernel, then multiply the
   result with adjacent sub-expressions using a multiply kernel.
2. **Left-solve**: When `inv(A)` is at the left boundary of a sub-expression and is
   combined with a right sub-expression `R`, use a left-solve kernel to compute
   `inv(A) @ R` directly as `solve(A, R)`.
3. **Right-solve**: When `inv(A)` is at the right boundary of a sub-expression and is
   combined with a left sub-expression `L`, use a right-solve kernel to compute
   `L @ inv(A)` directly as `right_solve(A, L)`.

The optimizer should choose whichever option minimizes total FLOPs.

## Output Format

For each problem, write `/app/output/<problem_id>.json`:

```json
{
  "problem_id": "problem_1",
  "total_flops": 40200000,
  "steps": [
    {
      "kernel": "DIAGMM",
      "operands": ["D", "B"],
      "output": "T0",
      "dims": [2000, 100],
      "flops": 200000
    },
    {
      "kernel": "GEMM",
      "operands": ["A", "T0"],
      "output": "RESULT",
      "dims": [100, 100],
      "flops": 40000000
    }
  ]
}
```

Requirements:
- `total_flops` must equal the sum of all step `flops` values.
- The last step's `output` must be `"RESULT"`.
- `dims` is `[rows, cols]` of the step's output matrix.
- For solve kernels (TRSM, GESV, POSV, DIAGSOLVE), `operands[0]` is the matrix
  being solved against (A in `solve(A, B)`), `operands[1]` is the right-hand side.
- For right-solve kernels (*_R), `operands[0]` is the left-hand side (B),
  `operands[1]` is the matrix being solved against (A in `B @ inv(A)`).
- For inverse kernels, `operands` has one element (the matrix to invert).
- For multiply kernels, `operands[0]` is left, `operands[1]` is right.
