# Optimal Brain Quantization (OBQ) Specification

## Overview

Post-training weight quantization reduces model storage and inference cost by
representing weights with fewer bits. Naive rounding ignores inter-weight
dependencies; OBQ uses second-order (Hessian) information from calibration data
to compensate quantization errors across columns, substantially reducing
reconstruction error.

## Uniform Quantization

**Symmetric** (b bits):
- q_max = 2^(b-1) - 1
- scale = max(|x|) / q_max
- Q(x) = clip(round(x / scale), -q_max, q_max) * scale

**Asymmetric** (b bits):
- q_max = 2^b - 1
- scale = (max(x) - min(x)) / q_max
- zero_point = clip(round(-min(x) / scale), 0, q_max)
- Q(x) = (clip(round(x / scale + zero_point), 0, q_max) - zero_point) * scale

Edge cases: return zeros if all inputs are zero (symmetric) or constant if
max equals min (asymmetric).

## Hessian Matrix

For a linear layer y = Wx with calibration inputs X in R^(N x d):

    H = 2 * X^T * X / N

H is symmetric positive semi-definite and captures the second-order sensitivity
of the squared reconstruction loss to weight perturbations.

## OBQ Algorithm

Given W in R^(m x d) and H in R^(d x d):

1. **Regularize**: H_d = H + lambda * mean(diag(H)) * I, where lambda is the
   damping factor (e.g. 0.01).

2. **Invert**: H_inv = H_d^(-1). Optionally use Cholesky for stability.

3. **Sequential quantization** (process columns left to right):

   For q = 0, 1, ..., d-1:

   (a) Quantize:  Q[:, q] = uniform_quantize(W[:, q], bits, symmetric=True)

   (b) Scaled error:  delta = (W[:, q] - Q[:, q]) / H_inv[q, q]

   (c) Compensate:  W[:, q+1:] -= delta (outer) H_inv[q, q+1:]

   The key insight: dividing by H_inv[q, q] and projecting onto H_inv[q, :]
   is the optimal least-squares adjustment that minimizes the Hessian-weighted
   impact of quantizing column q on the remaining columns.

4. **Reconstruction error**: E = trace((W_orig - Q) * H * (W_orig - Q)^T)

## Blocked OBQ

Process columns in blocks of size B for computational efficiency:

For each block [s, s+B):
  - Within the block, apply sequential quantization using the block sub-matrix
    H_inv[s:s+B, s:s+B] for within-block error compensation.
  - After the block, apply the accumulated cross-block update:
    W[:, s+B:] -= E_block @ H_inv[s:s+B, s+B:]
    where E_block collects the B scaled-error vectors as columns.

This is mathematically equivalent to column-by-column processing.

## Activation Order (act-order)

Instead of left-to-right column processing, sort columns by **descending**
diagonal of H. Columns with larger H_ii are more sensitive to quantization
error, so quantizing them first (when the full Hessian inverse is available
for compensation) typically reduces total error.

1. perm = argsort(diag(H), descending)
2. Permute W columns and H rows/columns by perm
3. Run standard OBQ on the permuted problem
4. Un-permute Q columns to restore original ordering

## Mixed-Precision Assignment

Given K layers with pre-computed quantization errors for each (layer, bit-width)
pair, find the bit-width assignment b_1, ..., b_K that minimizes total
quantization error subject to a storage budget:

    minimize   sum_k  error(k, b_k)
    subject to sum_k  rows_k * cols_k * b_k  <=  budget

This is a bounded knapsack problem solvable via dynamic programming over
(layer index, cumulative cost) states.
