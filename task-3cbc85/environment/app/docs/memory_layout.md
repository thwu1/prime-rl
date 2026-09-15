# Scaled Dot-Product Attention — Memory Layout

## Task

Implement a scaled dot-product attention kernel with causal masking for the VecTor-16 accelerator.

**Head dimension:** d_k = 32
**Sequence length:** seq_len = 8 (KV cache holds 8 key/value vectors)
**Vector register length:** 16 elements (d_k requires 2 tiles per vector)

## Memory Map

All addresses are in units of float64 values.

| Start | End | Size (floats) | Content | Access |
|---|---|---|---|---|
| 0 | 31 | 32 | Query vector **Q** | Read-only |
| 32 | 287 | 256 | Key cache **K[0..7]** (8 vectors of 32) | Read-only |
| 288 | 543 | 256 | Value cache **V[0..7]** (8 vectors of 32) | Read-only |
| 544 | 544 | 1 | **n_valid** (float): number of valid KV positions for causal mask | Read-only |
| 545 | 559 | 15 | (reserved padding) | — |
| 560 | 591 | 32 | **Output vector** (write result here) | Write |
| 592 | 65535 | varies | Scratch space (free to use) | Read/Write |

## Key/Value Cache Storage

K and V vectors are stored contiguously in row-major order:
- **K[i]** occupies addresses `32 + i*32` to `32 + i*32 + 31`
- **V[i]** occupies addresses `288 + i*32` to `288 + i*32 + 31`

All K[i] and V[i] base addresses are 16-aligned (since 32 is a multiple of 16).

## Computation

```
score[i] = dot(Q, K[i]) / sqrt(d_k)       for i = 0..7
score[i] = -infinity                        for i >= n_valid   (causal mask)
attn = softmax(score)                       (must be numerically stable)
output = sum_i( attn[i] * V[i] )           (weighted sum of value vectors)
```

Where:
- **dot(a, b)** = sum over j of a[j] * b[j]
- **softmax** converts scores to a probability distribution that sums to 1
- Masked positions (score = -infinity) must receive exactly zero attention weight
- The output is a 32-element vector

## Causal Mask

The value `n_valid` at address 544 indicates how many KV positions are valid. Positions with index `i >= n_valid` represent future tokens that must not be attended to. Set their scores to negative infinity before applying softmax, ensuring they receive zero attention weight.

## Alignment Notes

- All base addresses in this layout are multiples of 16
- Each K[i] and V[i] starts at a 16-aligned address (stride = 32)
- VLOAD/VSTORE require 16-aligned effective addresses; SLOAD/SSTORE have no alignment constraint
- Scratch space at address 592 is 16-aligned
