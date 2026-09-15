# Weighted Pairwise-Complete Pearson Correlation — Specification


## Overview

Given an n×m data matrix D (rows = variables, columns = observations) with a non-negative weight vector w ∈ ℝᵐ and possible NaN missing values, compute the weighted pairwise-complete Pearson correlation coefficient for every pair of rows and produce both a ranked text listing and a binary correlation matrix.

## Command-Line Interface

```
./correlation <input.bin> <K> <min_samples> <output.bin>
```

- `input.bin`: input file in CORR binary format (see below)
- `K`: number of top correlated pairs to print to stdout (integer ≥ 0)
- `min_samples`: minimum joint observation count for a valid correlation (integer ≥ 1)
- `output.bin`: output file path for RMAT binary format (see below)

## CORR Binary Input Format

All multi-byte values are little-endian.

| Offset | Size | Type | Description |
|--------|------|------|-------------|
| 0 | 4 | char[4] | Magic bytes: `"CORR"` (ASCII) |
| 4 | 4 | uint32 | n — number of rows |
| 8 | 4 | uint32 | m — number of columns |
| 12 | 8·m | float64[m] | Column weights w[0..m−1] |
| 12+8m | 8·n·m | float64[n·m] | Data matrix D, row-major. IEEE 754 NaN encodes missing values. |

## RMAT Binary Output Format

| Offset | Size | Type | Description |
|--------|------|------|-------------|
| 0 | 4 | char[4] | Magic bytes: `"RMAT"` (ASCII) |
| 4 | 4 | uint32 | n — number of rows |
| 8 | 8·P | float64[P] | Upper-triangle correlation values, P = n·(n−1)/2 |

Values are stored in row-major upper-triangle order:
r(0,1), r(0,2), …, r(0,n−1), r(1,2), r(1,3), …, r(n−2,n−1)

Undefined correlations are stored as IEEE 754 NaN.

## Computation

For a pair of rows (i, j) with i < j, let

  V(i,j) = { k ∈ [0, m) : D[i][k] ∉ NaN ∧ D[j][k] ∉ NaN }

denote the set of jointly valid columns and let W(i,j) = Σ_{k∈V} w[k].

Define the normalized weight for each valid column k as w̃_k = w[k] / W(i,j), the weighted means

  μ_i = Σ_{k∈V} w̃_k · D[i][k]  ,   μ_j = Σ_{k∈V} w̃_k · D[j][k]

and the weighted (co)variances

  σ²_i = Σ_{k∈V} w̃_k · (D[i][k] − μ_i)²  ,   σ²_j = Σ_{k∈V} w̃_k · (D[j][k] − μ_j)²

  C(i,j) = Σ_{k∈V} w̃_k · (D[i][k] − μ_i) · (D[j][k] − μ_j)

The correlation is then

  r(i,j) = C(i,j) / √(σ²_i · σ²_j)

**Undefined (NaN) conditions** — r(i,j) is NaN whenever any of:
- |V(i,j)| < min_samples
- W(i,j) = 0
- σ²_i = 0 or σ²_j = 0

Note: floating-point arithmetic may yield a tiny nonzero σ² for truly constant rows; implementations must treat effectively-zero variance as zero.

## Stdout Output

Print the top K pairs with highest correlation to stdout, one per line:

```
i j r
```

where i, j are 0-indexed (i < j) and r has at least 12 decimal places.

**Ordering**: descending by r; ties broken by i ascending, then j ascending. Only non-NaN pairs appear. If fewer than K valid pairs exist, print all of them.

## Exit

Return exit code 0 on success.
