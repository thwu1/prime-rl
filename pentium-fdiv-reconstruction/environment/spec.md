# Radix-4 SRT Division: Algorithm Specification

## Overview

The SRT (Sweeney-Robertson-Tocher) algorithm performs division by producing two quotient
bits per iteration using a redundant digit set. The Pentium uses radix-4 SRT with digit
set {-2, -1, 0, 1, 2}.

## Algorithm

Given dividend `a` and divisor `d`, both normalized significands in `[1.0, 2.0)`:

1. Initialize partial remainder: `w_0 = a`
2. For each step j = 1, 2, ..., n:
   - Look up quotient digit `q_j` from the P-D table using truncated `d` and `w_{j-1}`
   - Update: `w_j = 4 * (w_{j-1} - q_j * d)`
3. Quotient: `Q = q_1 + q_2 * 4^(-1) + q_3 * 4^(-2) + ...`

## Lookup Table Structure

The P-D (Partial remainder - Divisor) table has 2048 entries:

- **Divisor index** (`d_idx`): 4-bit value (0--15). The divisor `d` in `[1.0, 2.0)` is
  truncated to 4 fractional binary bits: `d_hat = 1 + d_idx/16`. So `d_idx = floor((d - 1) * 16)`.

- **Partial remainder index** (`p_idx`): 7-bit signed value (-64 to 63). The partial
  remainder `w` is truncated to 3 fractional binary bits: `p_hat = p_idx / 8`. So
  `p_idx = floor(w * 8)` (using floor toward negative infinity for negative values).

- **Output**: quotient digit `q` in `{-2, -1, 0, 1, 2}`.

## Selection Function Bounds

For radix r=4 with digit set {-2, -1, 0, 1, 2}, a quotient digit `q` is valid when
the resulting next partial remainder stays in the convergence range `[-rho*d, rho*d]`
where `rho = 8/3` (after scaling by r=4).

The valid ranges for each digit are derived from `|4 * (w - q*d)| <= (8/3)*d`:

| Digit q | Valid range for w                |
|---------|----------------------------------|
| +2      | `(4/3)*d  <=  w  <=  (8/3)*d`   |
| +1      | `(1/3)*d  <=  w  <=  (5/3)*d`   |
|  0      | `-(2/3)*d <=  w  <=  (2/3)*d`   |
| -1      | `-(5/3)*d <=  w  <= -(1/3)*d`   |
| -2      | `-(8/3)*d <=  w  <= -(4/3)*d`   |

Note the overlap (redundancy) regions where two adjacent digits are both valid:
- q=1 or q=2: `(4/3)*d <= w <= (5/3)*d`
- q=0 or q=1: `(1/3)*d <= w <= (2/3)*d`
- (and symmetric for negative)

## Carry-Save Adder and Table Indexing

The Pentium uses a carry-save adder internally. The table index `p_idx` is computed
by truncating (floor toward -infinity) the partial remainder to 3 fractional binary bits:
`p_idx = floor(w * 8)`, so `p_hat = p_idx / 8`.

This means the ACTUAL partial remainder `w_actual` lies in `[p_hat, p_hat + 1/8)`.
Each cell's quotient digit `q` must be a valid choice for ALL actual values in this range.

This truncation is asymmetric:
- For **positive** `p_hat`: the actual `w` is at least `p_hat` and at most `p_hat + 1/8`.
  Lower bounds (`w >= L*d`) only need `p_hat >= L*d` (automatic since `p_hat <= w`).
  The outermost upper bound (`w <= (8/3)*d`) is guaranteed by the algorithm invariant.
- For **negative** `p_hat`: the actual `w` ranges from `p_hat` (most negative) to
  `p_hat + 1/8` (least negative). For a threshold like `w <= -(1/3)*d`, even the
  LEAST negative value must satisfy this: `p_hat + 1/8 <= -(1/3)*d`, i.e.,
  `p_hat <= -(1/3)*d - 1/8`.

## Table Construction Rules

For each cell `(d_idx, p_idx)`:

1. Compute `d = 1 + d_idx/16` and `p = p_idx/8`.

2. If `|p| > (8/3)*d` (correct) or `|p| > (8/3)*d - 1/8` (buggy), the cell is
   **unused**. Set `q = 0`.

3. Otherwise, **prefer the digit with highest absolute value** (bias toward higher
   digits):

   For `p >= 0`:
   - `q = +2` if `p >= (4/3)*d` (no upper adjustment needed; algorithm invariant
     guarantees actual `w <= (8/3)*d`)
   - `q = +1` if `p >= (1/3)*d` and `p < (4/3)*d`
   - `q = 0`  if `p < (1/3)*d`

   For `p < 0` (adjusted for carry-save truncation):
   - `q = -2` if `p <= -(4/3)*d - 1/8`
   - `q = -1` if `p <= -(1/3)*d - 1/8` and `p > -(4/3)*d - 1/8`
   - `q = 0`  if `p > -(1/3)*d - 1/8`

## The Pentium Bug

The Pentium's lookup table had a mathematical error in the **upper boundary** of the
valid partial remainder range. The boundary between the `q=+2` region and the unused
region (and symmetrically for `q=-2`) was defined incorrectly.

### Correct boundary
The correct outer bound of the valid range is: `|p| <= (8/3) * d`

Cells with `|p| > (8/3)*d` are genuinely unreachable and should be set to 0.
Cells with `|p| <= (8/3)*d` and in a valid digit range should be set to that digit.

The outer boundary does NOT need carry-save adjustment because the algorithm's own
invariant guarantees the actual partial remainder stays within `(8/3)*d`. The
carry-save truncation only affects whether the CELL INDEX is one lower, not whether
the actual value is valid.

### Intel's error
Intel incorrectly applied the carry-save truncation adjustment to the outer boundary:
`|p| <= (8/3)*d - 1/8`

This adjustment is correct for the INNER boundaries (where it ensures validity of `q`
for the full cell range), but should NOT have been applied to the outermost boundary.
The effect is that cells with `(8/3)*d - 1/8 < |p| <= (8/3)*d` are incorrectly
left as 0 (unused) when they should contain `+/-2`.

When the SRT algorithm accesses one of these missing cells, it gets `q=0` instead of
`q=+/-2`. This causes the partial remainder to jump to `4*w` instead of `4*(w - 2d)`,
overshooting the valid range by approximately `8d`, and corrupting subsequent quotient
digits.

## Quotient Conversion

The quotient digits `q_1, q_2, ...` are in redundant form. Convert to a standard
floating-point value:

```
Q = sum(q_j * 4^(1-j)) for j = 1, 2, ..., n
  = q_1 + q_2/4 + q_3/16 + ...
```

## Numerical Precision

Use Python's `fractions.Fraction` for exact arithmetic when generating lookup tables
to avoid floating-point comparison errors. The table generation involves comparing values
like `p` against `(4/3)*d` where exact rational arithmetic is essential.
