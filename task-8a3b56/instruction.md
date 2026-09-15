Implement all functions in `/app/quantlib/core.py` to create a working 4-bit quantization library for neural network weights. A mathematical reference document is at `/app/spec.md`. The `QuantState` class is already provided — do not modify it.

## Functions to Implement

### `create_nf4_map(offset=0.9677083) -> torch.Tensor`

Produce a sorted float32 tensor — the NF4 codebook. Required properties:

- Exactly 16 elements with 16 unique values
- Value range: [-1, 1] (minimum is -1.0, maximum is 1.0)
- Contains exactly 1 exact zero, 8 positive values, and 7 negative values
- The smallest positive value must be less than 0.15
- Deterministic: repeated calls return identical results

### `create_fp4_map() -> torch.Tensor`

Produce a sorted float32 tensor — the FP4 codebook. Required properties:

- Exactly 16 elements with 15 unique values (two representable zeros collapse)
- Value range: [-1, 1]
- Contains at least one exact zero
- Symmetric: equal count of positive and negative values
- Deterministic

### `quantize_4bit(A, blocksize=64, quant_type="nf4", compress_statistics=False)`

Returns `(packed_tensor, quant_state)`. Quantize tensor `A` to 4-bit representation using blockwise scaling. Must support `quant_type` values `"nf4"` and `"fp4"`, and blocksizes 32, 64, 128, and 256.

**Packed tensor requirements:**
- dtype: `torch.uint8`
- Size: `ceil(A.numel() / 2)` elements (two 4-bit indices per byte)

**Dtype preservation:** dequantizing a quantized tensor must recover the original dtype. Must work for `torch.float32`, `torch.float16`, and `torch.bfloat16`.

**Zero-tensor invariant:** an all-zero input must roundtrip to all zeros (max absolute error < 1e-6).

**`QuantState` fields (standard mode, `compress_statistics=False`):**
- `shape`: original tensor shape
- `blocksize`: the block size used
- `quant_type`: `"nf4"` or `"fp4"`
- `dtype`: original tensor dtype
- `code`: the codebook tensor
- `nested`: must be `False`

**Roundtrip accuracy** on `torch.randn(1024, 1024)` with seed 42, blocksize 64:
- NF4: mean absolute error < 0.10
- FP4: mean absolute error < 0.12
- All blocksizes (32, 64, 128, 256): error < 0.12

NF4 must achieve strictly lower mean absolute error than FP4 on normally-distributed data.

**Double quantization** (`compress_statistics=True`): the per-block quantization constants are further compressed to reduce memory overhead. When enabled, `QuantState` must satisfy:
- `nested` is `True`
- `state2` is not `None`
- `offset` is not `None`
- `absmax` dtype is `torch.uint8`
- Roundtrip mean absolute error < 0.10
- Roundtrip error must be within 1.5× of the standard (non-compressed) error

### `dequantize_4bit(A, quant_state) -> torch.Tensor`

Recover the original tensor from its packed 4-bit representation and quantization state. Output shape and dtype must match the original tensor.

### `compute_memory_bits_per_param(blocksize=64, double_quant=False, dq_blocksize=256) -> float`

Return the average bits per parameter for the quantized representation, accounting for 4-bit weight storage and the overhead of per-block quantization constants (stored as float32 scaling factors). With double quantization, the first-level constants are stored in a more compact format with their own second-level float32 constants grouped by `dq_blocksize`. Double quantization must always use fewer bits than standard quantization for the same blocksize.