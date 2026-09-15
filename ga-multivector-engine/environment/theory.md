# Geometric Algebra: Mathematical Reference

## Basis and Blades

Given n basis vectors e_0, e_1, ..., e_{n-1}, the 2^n basis blades are formed
by all ordered products of distinct basis vectors. Each blade is identified by
a bitmask where bit k indicates the presence of e_k. The grade of a blade is
the number of basis vectors it contains (popcount of the bitmask). The scalar
(grade 0) has bitmask 0. The pseudoscalar (grade n) has bitmask 2^n - 1.

## Multivector Representation

A multivector is a real linear combination of basis blades, stored as an array
of 2^n real coefficients ordered by ascending grade. Within each grade, blades
follow a fixed ordering convention determined by the `mask_tables` function.
The function `mask_tables(dims)` returns a pair `(mask_table, inv_mask_table)`:
- `mask_table[position]` = the bitmask of the blade stored at that position.
- `inv_mask_table[bitmask]` = the position where that blade is stored.

The within-grade ordering is established by sweeping dimensions from high to
low: in each sweep step, blades containing that basis vector are stably sorted
before those that do not.

## Metric Signatures

The metric determines how each basis vector squares under the geometric product:

- **VGA** (Euclidean): e_i^2 = 1 for all i.
- **PGA** (Projective): e_0^2 = 0; e_i^2 = 1 for i > 0.
  The lowest-index basis vector is degenerate.
- **Cl(p, q, r)** (General Clifford): The first r basis vectors (indices
  0..r-1) square to 0; the next q (indices r..r+q-1) square to -1; the
  remaining p square to +1.

Flavor encoding in function arguments:
- `"VGA"` for Euclidean
- `"PGA"` for Projective
- `("Cl", p, q, r)` tuple for general Clifford

## Geometric Product

The geometric product is the fundamental operation of geometric algebra,
defined by three axioms applied to basis vectors:

1. **Associativity**: (AB)C = A(BC)
2. **Basis vector contraction**: e_i * e_i = metric(i)
3. **Anticommutativity of distinct basis vectors**: e_i * e_j = -e_j * e_i for i != j

The product is extended to arbitrary multivectors by distributivity.

For two basis blades with bitmasks a and b, their geometric product yields:
- Result bitmask: a XOR b (shared basis vectors cancel via contraction)
- A sign factor from the number of transpositions needed to bring the
  combined basis vector sequence into canonical (ascending index) order
- A metric factor: the product of metric(k) for each basis vector k that
  appears in both blades (the shared/common basis vectors, i.e. a AND b)

If any shared basis vector has metric 0, the entire product term vanishes.

## Outer (Wedge) Product

The outer product retains only grade-additive terms from the geometric product.
For input blades of grades g_i and g_j, only terms with result grade equal to
g_i + g_j are kept. This is equivalent to discarding terms where the two input
blades share any basis vectors.

Properties:
- Anticommutative for grade-1 elements: e_i ^ e_j = -e_j ^ e_i
- e_i ^ e_i = 0
- Associative

## Inner Product (Hestenes)

The Hestenes inner product retains only grade-lowering terms. For non-scalar
input blades of grades g_i and g_j (both > 0), only terms with result grade
|g_i - g_j| are kept. Scalar (grade 0) blades contribute nothing to the
Hestenes inner product.

Properties:
- e_i . e_j = 0 for distinct basis vectors i != j
- e_i . e_i = metric(i)
- For a blade A of grade s and blade B of grade r with s <= r:
  A . B has grade r - s

## Reverse

The reverse of a multivector negates each component of grade k by the factor
(-1)^(k(k-1)/2). This corresponds to reversing the order of basis vectors
in each blade product: (e_i e_j e_k)~ = e_k e_j e_i.

Sign pattern by grade: +1, +1, -1, -1, +1, +1, -1, -1, ...

## Grade Projection

Extract only components of a specified grade, zeroing all others.

## Grade Involution (Main Involution)

Negate all odd-grade components. Each component of grade k is multiplied
by (-1)^k.

Sign pattern by grade: +1, -1, +1, -1, +1, -1, ...

## Sandwich Product

The sandwich product applies a transformation element R to a multivector x:

    sandwich(R, x) = R * x * reverse(R)

where * denotes the geometric product. This is the standard mechanism for
rotations (using rotor R = cos(theta/2) - sin(theta/2) * B where B is a
unit bivector) and reflections in geometric algebra.
