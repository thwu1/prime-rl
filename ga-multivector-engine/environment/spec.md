# Geometric Algebra Engine Specification

## Overview

Implement a Python module at `/app/ga_engine.py` that provides geometric algebra
(GA) operations on multivectors in n dimensions (n <= 6). A multivector in n
dimensions is represented as a flat list of 2^n real-valued coefficients, one per
basis blade, ordered according to a specific convention defined below.

## Blade Ordering (Mask Tables)

Each of the 2^n basis blades corresponds to a subset of basis vectors
{e_0, e_1, ..., e_{n-1}}, encoded as a bitmask where bit k being set indicates
the presence of basis vector e_k. The grade of a blade is the number of basis
vectors it contains (i.e., the popcount of its bitmask).

Blades are arranged in the multivector coefficient array using a particular
stable-sort algorithm:

1. Initialize the table as the sequence [0, 1, 2, ..., 2^n - 1].
2. For each dimension d from (n-1) down to 0 inclusive, perform a **stable**
   sort that places bitmasks with bit d **set** before those with bit d
   **unset**.
3. Perform one final **stable** sort by ascending grade (popcount).

The function `mask_tables(dims)` must return a pair `(mask_table, inv_mask_table)`:
- `mask_table[position]` = the bitmask of the blade stored at that position.
- `inv_mask_table[bitmask]` = the position where that blade is stored.

### Example (dims=3)

After the algorithm, the mask table is `[0, 1, 2, 4, 3, 5, 6, 7]`:

| Position | Bitmask | Blade   | Grade |
|----------|---------|---------|-------|
| 0        | 0 (000) | scalar  | 0     |
| 1        | 1 (001) | e_0     | 1     |
| 2        | 2 (010) | e_1     | 1     |
| 3        | 4 (100) | e_2     | 1     |
| 4        | 3 (011) | e_01    | 2     |
| 5        | 5 (101) | e_02    | 2     |
| 6        | 6 (110) | e_12    | 2     |
| 7        | 7 (111) | e_012   | 3     |

## Metric Flavors

The metric determines how each basis vector squares under the geometric product:

- **VGA** (Euclidean): `metric(i) = 1` for all i. Every e_k squares to +1.
- **PGA** (Projective): `metric(0) = 0`; `metric(i) = 1` for i > 0.
  The lowest-index basis vector is degenerate (e_0^2 = 0).
- **Cl(p, q, r)** (General Clifford): The first `r` basis vectors (indices
  0..r-1) square to 0; the next `q` (indices r..r+q-1) square to -1; the
  remaining `p` square to +1.

Flavor encoding in function arguments:
- `"VGA"` for Euclidean
- `"PGA"` for Projective
- `("Cl", p, q, r)` tuple for general Clifford

## Canonical Reorder Sign

When multiplying two basis blades with bitmasks `a` and `b`, the result blade
has bitmask `a XOR b`, but a sign factor arises from the number of adjacent-
element transpositions needed to merge the two sorted basis-vector lists into
one.

**Algorithm for `reorder_sign(a, b)`:**
```
shifted = a >> 1
count   = 0
while shifted != 0:
    count   += popcount(shifted AND b)
    shifted >>= 1
return +1 if count is even, -1 if count is odd
```

## Geometric Product

For multivectors A and B of dimension n with flavor F, the geometric product
C = A * B is:

```
for every position pair (i, j) in [0, 2^n):
    mask_i, mask_j = mask_table[i], mask_table[j]
    sign           = reorder_sign(mask_i, mask_j)
    common         = mask_i AND mask_j
    met            = product of metric(F, bit) for each set bit in common
                     (equals 1 when common is 0)
    if met == 0: skip
    result_pos     = inv_mask_table[mask_i XOR mask_j]
    C[result_pos] += sign * met * A[i] * B[j]
```

**Signature:** `geo_product(mv_a, mv_b, dims, flavor="VGA") -> list[float]`

## Outer (Wedge) Product

Identical to the geometric product, but **only accumulate** a term when
`grade(result_mask) == grade(mask_i) + grade(mask_j)`.

(Because shared bits reduce the result grade, this condition is equivalent to
requiring that mask_i and mask_j share no set bits.)

**Signature:** `outer_product(mv_a, mv_b, dims, flavor="VGA") -> list[float]`

## Inner Product (Hestenes)

Identical to the geometric product, but **only accumulate** a term when:
1. `grade(mask_i) > 0` **and** `grade(mask_j) > 0`, and
2. `grade(result_mask) == |grade(mask_i) - grade(mask_j)|`.

Scalar blades contribute nothing to the inner product.

**Signature:** `inner_product(mv_a, mv_b, dims, flavor="VGA") -> list[float]`

## Reverse

The reverse of a multivector negates each blade of grade k by the factor
`(-1)^(k*(k-1)/2)`:

| Grade | Factor |
|-------|--------|
| 0     | +1     |
| 1     | +1     |
| 2     | -1     |
| 3     | -1     |
| 4     | +1     |
| 5     | +1     |

**Signature:** `reverse_mv(mv, dims) -> list[float]`

## Grade Projection

Extract only the components whose blade has a given grade; zero out all others.

**Signature:** `grade_project(mv, grade, dims) -> list[float]`

## Utility Functions

- `blade_grade(bitmask) -> int` — popcount of the bitmask.
- `metric(flavor, bit_index) -> int` — metric value for the given flavor and
  basis-vector index.

## Summary of Required Exports

```
mask_tables(dims)
blade_grade(bitmask)
reorder_sign(mask_a, mask_b)
metric(flavor, bit_index)
geo_product(mv_a, mv_b, dims, flavor="VGA")
outer_product(mv_a, mv_b, dims, flavor="VGA")
inner_product(mv_a, mv_b, dims, flavor="VGA")
reverse_mv(mv, dims)
grade_project(mv, grade, dims)
```
