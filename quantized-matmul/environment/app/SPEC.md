# Block-Quantized INT8 Matrix Multiplication — Specification


## Overview

This library performs matrix multiplication C = A * B by:
1. Partitioning A and B into blocks of size `block_size x block_size`
2. Quantizing each block independently from float32 to INT8
3. Computing the matmul using INT8 arithmetic with INT32 accumulators
4. Dequantizing the accumulated results back to float32

Two quantization modes are supported: **symmetric** and **asymmetric**.

## Symmetric Quantization

For a block of float32 values {x_ij}:

```
absmax = max over all i,j of |x_ij|

if absmax == 0:
    scale = 1.0
else:
    scale = absmax / 127.0

q_ij = clamp(round(x_ij / scale), -128, 127)
```

Dequantization: `x'_ij = q_ij * scale`

Maximum per-element roundtrip error: `scale / 2`

## Asymmetric Quantization

For a block of float32 values {x_ij}:

```
x_min = min over all i,j of x_ij
x_max = max over all i,j of x_ij

if x_min == x_max:
    scale = 1.0
    zero_point = x_min
    all q_ij = 0
else:
    scale = (x_max - x_min) / 254.0
    zero_point = (x_max + x_min) / 2.0
    q_ij = clamp(round((x_ij - zero_point) / scale), -127, 127)
```

Dequantization: `x'_ij = q_ij * scale + zero_point`

The zero_point represents the center of the value range. Asymmetric quantization
is more accurate than symmetric for distributions that are not centered around zero.

## Quantized Matrix Multiplication — Symmetric Mode

```
Initialize C[M x N] = 0

For each K-tile:  k_start in range(0, K, block_size)
    bk = min(block_size, K - k_start)

    For each M-tile:  m_start in range(0, M, block_size)
        bm = min(block_size, M - m_start)

        Quantize A_block = A[m_start : m_start+bm, k_start : k_start+bk]
        Note: A is row-major with stride K, so pass K as src_stride
        → qa[bm][bk] (INT8), scale_a (float)

        For each N-tile:  n_start in range(0, N, block_size)
            bn = min(block_size, N - n_start)

            Quantize B_block = B[k_start : k_start+bk, n_start : n_start+bn]
            Note: B is row-major with stride N, so pass N as src_stride
            → qb[bk][bn] (INT8), scale_b (float)

            For i in [0, bm):
                For j in [0, bn):
                    int32 acc = 0
                    For kk in [0, bk):
                        acc += (int32)qa[i*bk + kk] * (int32)qb[kk*bn + j]

                    C[(m_start+i)*N + (n_start+j)] += (float)acc * scale_a * scale_b
```

## Quantized Matrix Multiplication — Asymmetric Mode

In asymmetric mode, dequantized values are `a' = qa * sa + zpa` and `b' = qb * sb + zpb`.

The product expands as:
```
a' * b' = (qa*sa + zpa)(qb*sb + zpb)
        = sa*sb * qa*qb  +  sa*zpb * qa  +  zpa*sb * qb  +  zpa*zpb
```

Summing over k within a tile of size bk:

```
Σ_k a'[i,k] * b'[k,j] = sa*sb * Σ_k qa[i,k]*qb[k,j]       ... Term 1: INT8 matmul
                        + sa*zpb * Σ_k qa[i,k]                ... Term 2: row sum of qa
                        + zpa*sb * Σ_k qb[k,j]                ... Term 3: col sum of qb
                        + bk * zpa * zpb                       ... Term 4: constant
```

## Edge Blocks

When matrix dimensions are not divisible by `block_size`, the last block in each
dimension will be smaller than `block_size`. All functions must handle these edge
blocks correctly. The actual block dimensions for the last tile are:

- M direction: `bm = min(block_size, M - m_start)`
- K direction: `bk = min(block_size, K - k_start)`
- N direction: `bn = min(block_size, N - n_start)`

## Sub-block Addressing

When extracting a sub-block from a larger matrix for quantization, the source pointer
must be offset to the start of the block, and the source stride must equal the full
matrix width (not the block width). For example:

- To quantize `A[m_start:m_end, k_start:k_end]`:
  - `src = A + m_start * K + k_start`
  - `src_stride = K`
  - `rows = bm, cols = bk`

- To quantize `B[k_start:k_end, n_start:n_end]`:
  - `src = B + k_start * N + n_start`
  - `src_stride = N`
  - `rows = bk, cols = bn`

## Memory Management

The `quantized_matmul` function must allocate temporary buffers for quantized blocks,
row sums, and column sums. These should be freed before return. Maximum temporary
buffer size per block is `block_size * block_size` bytes (INT8).

---

## Adaptive Quantized Matrix Multiplication

`adaptive_quantized_matmul` follows the same tiling structure as `quantized_matmul`
but independently selects the quantization mode for each tile.

### Requirements

1. Signature and behavior match the declaration in `qmatmul.h`
2. Results are correct (within quantization tolerance) for arbitrary matrix
   dimensions, block sizes, and data distributions
3. On data distributions with significant bias (e.g., all-positive values),
   adaptive must achieve lower error than uniform symmetric quantization
4. Edge blocks (dimensions not divisible by block_size) must be handled correctly
5. If `stats` is non-NULL, `stats[0]` and `stats[1]` must report the count of
   symmetric and asymmetric tile quantizations performed (A and B tiles combined)
