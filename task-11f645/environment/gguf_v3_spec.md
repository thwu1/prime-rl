# GGUF v3 Binary Format Specification (Reference)

## Overview

GGUF is a binary format for storing ML models for inference with GGML-based engines.
All multi-byte values are little-endian. Padding uses `0x00` bytes.

## Type Enumerations

### Tensor Data Types (`ggml_type`, encoded as `uint32_t`)

| Value | Name            | Block Size | Bytes/Block | Description                        |
|-------|-----------------|------------|-------------|------------------------------------|
| 0     | GGML_TYPE_F32   | 1          | 4           | 32-bit IEEE 754 float              |
| 1     | GGML_TYPE_F16   | 1          | 2           | 16-bit IEEE 754 float              |
| 2     | GGML_TYPE_Q4_0  | 32         | 18          | 4-bit quantization (symmetric)     |
| 3     | GGML_TYPE_Q4_1  | 32         | 20          | 4-bit quantization (asymmetric)    |
| 6     | GGML_TYPE_Q5_0  | 32         | 22          | 5-bit quantization (symmetric)     |
| 7     | GGML_TYPE_Q5_1  | 32         | 24          | 5-bit quantization (asymmetric)    |
| 8     | GGML_TYPE_Q8_0  | 32         | 34          | 8-bit quantization (symmetric)     |
| 9     | GGML_TYPE_Q8_1  | 32         | 36          | 8-bit quantization (asymmetric)    |
| 10    | GGML_TYPE_Q2_K  | 256        | 82          | K-quant 2-bit                      |
| 11    | GGML_TYPE_Q3_K  | 256        | 110         | K-quant 3-bit                      |
| 12    | GGML_TYPE_Q4_K  | 256        | 144         | K-quant 4-bit                      |
| 13    | GGML_TYPE_Q5_K  | 256        | 176         | K-quant 5-bit                      |
| 14    | GGML_TYPE_Q6_K  | 256        | 210         | K-quant 6-bit                      |
| 15    | GGML_TYPE_Q8_K  | 256        | 292         | K-quant 8-bit                      |
| 30    | GGML_TYPE_BF16  | 1          | 2           | Brain float 16                     |

### Metadata Value Types (`gguf_metadata_value_type`, encoded as `uint32_t`)

| Value | Name    | Size (bytes) | Description                              |
|-------|---------|--------------|------------------------------------------|
| 0     | UINT8   | 1            | 8-bit unsigned integer                   |
| 1     | INT8    | 1            | 8-bit signed integer                     |
| 2     | UINT16  | 2            | 16-bit unsigned little-endian integer    |
| 3     | INT16   | 2            | 16-bit signed little-endian integer      |
| 4     | UINT32  | 4            | 32-bit unsigned little-endian integer    |
| 5     | INT32   | 4            | 32-bit signed little-endian integer      |
| 6     | FLOAT32 | 4            | 32-bit IEEE 754 float                    |
| 7     | BOOL    | 1            | Boolean (0=false, 1=true)                |
| 8     | STRING  | variable     | Length-prefixed UTF-8 string             |
| 9     | ARRAY   | variable     | Typed array with length                  |
| 10    | UINT64  | 8            | 64-bit unsigned little-endian integer    |
| 11    | INT64   | 8            | 64-bit signed little-endian integer      |
| 12    | FLOAT64 | 8            | 64-bit IEEE 754 float                    |

**Important**: UINT32 (type=4) occupies 4 bytes; UINT64 (type=10) occupies 8 bytes.
Using the wrong type tag causes a 4-byte offset error in subsequent parsing.

## Binary Structures

### String (`gguf_string_t`)

```
uint64_t len;       // Length in bytes
char string[len];   // UTF-8 encoded, NO null terminator
```

Strings are NOT null-terminated. The length prefix is always `uint64_t` (8 bytes).

### Metadata Key-Value Pair (`gguf_metadata_kv_t`)

```
gguf_string_t key;                     // Hierarchical ASCII key (e.g., "general.name")
uint32_t      value_type;              // One of gguf_metadata_value_type
<value>                                // Encoded according to value_type
```

For **ARRAY** values, the encoding is:
```
uint32_t element_type;     // Type tag for all elements (must be homogeneous)
uint64_t count;            // Number of elements
element[count];            // Each element encoded by element_type
```

### Header (`gguf_header_t`)

```
uint32_t magic;                // Bytes: 0x47 0x47 0x55 0x46 ("GGUF" in ASCII)
uint32_t version;              // Must be 3 for GGUF v3
uint64_t tensor_count;         // Number of tensors in the file
uint64_t metadata_kv_count;    // Number of metadata key-value pairs
gguf_metadata_kv_t metadata_kv[metadata_kv_count];
```

The header occupies bytes 0-23 (fixed fields), followed by the metadata KV pairs.

| Offset | Size | Field              |
|--------|------|--------------------|
| 0      | 4    | magic              |
| 4      | 4    | version            |
| 8      | 8    | tensor_count       |
| 16     | 8    | metadata_kv_count  |
| 24     | var  | metadata KV pairs  |

### Tensor Info (`gguf_tensor_info_t`)

```
gguf_string_t name;                    // Tensor name (max 64 bytes)
uint32_t      n_dimensions;            // Number of dimensions (1-4)
uint64_t      dimensions[n_dimensions]; // Dimension sizes
uint32_t      type;                    // ggml_type enum value
uint64_t      offset;                  // Offset RELATIVE to tensor_data start
```

**Critical**: The `offset` field is relative to the start of the tensor data section,
NOT the start of the file.

### Complete File Layout

```
[Header: magic + version + tensor_count + kv_count + metadata KV pairs]
[Tensor Info: tensor_infos[tensor_count]]
[Padding: 0x00 bytes to next multiple of ALIGNMENT]
[Tensor Data: raw tensor bytes at aligned offsets]
```

## Alignment Rules

- The global alignment value is stored in `general.alignment` (uint32). Default: 32.
- Must be a multiple of 8.
- Between the end of tensor info and the start of tensor data: pad with `0x00`
  bytes to the next multiple of ALIGNMENT.
- Each tensor's data `offset` must be a multiple of ALIGNMENT.
- Inter-tensor gaps should be padded with `0x00` to ALIGNMENT.
- **All padding bytes MUST be `0x00`.**

## Q4_0 Quantization

Block size: 32 float values → 18 bytes per block.

Block layout:
- 2 bytes: FP16 scale factor `d`
- 16 bytes: 4-bit quantized values (two per byte, nibble-packed)

Quantization (per block of 32 floats):
1. Find value with largest absolute value → `max` (preserving sign)
2. `d = max / -8`
3. `id = 1/d` (or 0 if d=0)
4. For j in 0..15:
   - `xi0 = clamp(round(input[j] * id + 8.5), 0, 15)`       (first half)
   - `xi1 = clamp(round(input[j+16] * id + 8.5), 0, 15)`     (second half)
   - `byte[j] = xi0 | (xi1 << 4)`

Low nibble = first half element; high nibble = second half element.

## Required Metadata Keys

- **`general.architecture: string`** — model architecture (e.g., "llama")
- **`general.alignment: uint32`** — global alignment value
- **`general.quantization_version: uint32`** — required if quantized tensors exist

## LLaMA Architecture Required Keys

- `llama.context_length: uint64`
- `llama.embedding_length: uint64`
- `llama.block_count: uint64`
- `llama.feed_forward_length: uint64`
- `llama.rope.dimension_count: uint64`
- `llama.attention.head_count: uint64`
- `llama.attention.layer_norm_rms_epsilon: float32`

## Version History

- **v3**: Current version. Adds big-endian support.
- **v2**: Changed most countable values from uint32 to uint64.
- **v1**: Initial version.
