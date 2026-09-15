# GGUF Specification

GGUF is a binary file format for storing models for inference with GGML and executors based on GGML.
It is designed for fast loading and saving via `mmap`, extensibility through key-value metadata,
and single-file deployment.

## Binary Layout

GGUF files are structured as follows. They use a global alignment specified in the
`general.alignment` metadata field, referred to as `ALIGNMENT` below. Where required,
the file is padded with `0x00` bytes to the next multiple of `ALIGNMENT`.

Fields, including arrays, are written sequentially without alignment unless otherwise specified.

Models are **little-endian** by default.

### Enums

```c
enum ggml_type: uint32_t {
    GGML_TYPE_F32     = 0,
    GGML_TYPE_F16     = 1,
    GGML_TYPE_Q4_0    = 2,
    GGML_TYPE_Q4_1    = 3,
    GGML_TYPE_Q5_0    = 6,
    GGML_TYPE_Q5_1    = 7,
    GGML_TYPE_Q8_0    = 8,
    GGML_TYPE_Q8_1    = 9,
    GGML_TYPE_Q2_K    = 10,
    GGML_TYPE_Q3_K    = 11,
    GGML_TYPE_Q4_K    = 12,
    GGML_TYPE_Q5_K    = 13,
    GGML_TYPE_Q6_K    = 14,
    GGML_TYPE_Q8_K    = 15,
    GGML_TYPE_IQ2_XXS = 16,
    GGML_TYPE_IQ2_XS  = 17,
    GGML_TYPE_IQ3_XXS = 18,
    GGML_TYPE_IQ1_S   = 19,
    GGML_TYPE_IQ4_NL  = 20,
    GGML_TYPE_IQ3_S   = 21,
    GGML_TYPE_IQ2_S   = 22,
    GGML_TYPE_IQ4_XS  = 23,
    GGML_TYPE_I8      = 24,
    GGML_TYPE_I16     = 25,
    GGML_TYPE_I32     = 26,
    GGML_TYPE_I64     = 27,
    GGML_TYPE_F64     = 28,
    GGML_TYPE_IQ1_M   = 29,
    GGML_TYPE_BF16    = 30,
    GGML_TYPE_TQ1_0   = 34,
    GGML_TYPE_TQ2_0   = 35,
};

enum gguf_metadata_value_type: uint32_t {
    // The value is a 8-bit unsigned integer.
    GGUF_METADATA_VALUE_TYPE_UINT8 = 0,
    // The value is a 8-bit signed integer.
    GGUF_METADATA_VALUE_TYPE_INT8 = 1,
    // The value is a 16-bit unsigned little-endian integer.
    GGUF_METADATA_VALUE_TYPE_UINT16 = 2,
    // The value is a 16-bit signed little-endian integer.
    GGUF_METADATA_VALUE_TYPE_INT16 = 3,
    // The value is a 32-bit unsigned little-endian integer.
    GGUF_METADATA_VALUE_TYPE_UINT32 = 4,
    // The value is a 32-bit signed little-endian integer.
    GGUF_METADATA_VALUE_TYPE_INT32 = 5,
    // The value is a 32-bit IEEE754 floating point number.
    GGUF_METADATA_VALUE_TYPE_FLOAT32 = 6,
    // The value is a boolean.
    // 1-byte value where 0 is false and 1 is true.
    GGUF_METADATA_VALUE_TYPE_BOOL = 7,
    // The value is a UTF-8 non-null-terminated string, with length prepended.
    GGUF_METADATA_VALUE_TYPE_STRING = 8,
    // The value is an array of other values, with the length and type prepended.
    //
    // Arrays can be nested, and the length of the array is the number of
    // elements in the array, not the number of bytes.
    GGUF_METADATA_VALUE_TYPE_ARRAY = 9,
    // The value is a 64-bit unsigned little-endian integer.
    GGUF_METADATA_VALUE_TYPE_UINT64 = 10,
    // The value is a 64-bit signed little-endian integer.
    GGUF_METADATA_VALUE_TYPE_INT64 = 11,
    // The value is a 64-bit IEEE754 floating point number.
    GGUF_METADATA_VALUE_TYPE_FLOAT64 = 12,
};
```

### Data Structures

```c
// A string in GGUF.
struct gguf_string_t {
    // The length of the string, in bytes.
    uint64_t len;
    // The string as a UTF-8 non-null-terminated string.
    char string[len];
};

union gguf_metadata_value_t {
    uint8_t uint8;
    int8_t int8;
    uint16_t uint16;
    int16_t int16;
    uint32_t uint32;
    int32_t int32;
    float float32;
    uint64_t uint64;
    int64_t int64;
    double float64;
    bool bool_;
    gguf_string_t string;
    struct {
        // Any value type is valid, including arrays.
        gguf_metadata_value_type type;
        // Number of elements, not bytes
        uint64_t len;
        // The array of values.
        gguf_metadata_value_t array[len];
    } array;
};

struct gguf_metadata_kv_t {
    // The key of the metadata. It is a standard GGUF string, with the following caveats:
    // - It must be a valid ASCII string.
    // - It must be a hierarchical key, where each segment is `lower_snake_case`
    //   and separated by a `.`.
    // - It must be at most 2^16-1/65535 bytes long.
    gguf_string_t key;

    // The type of the value.
    // Must be one of the `gguf_metadata_value_type` values.
    gguf_metadata_value_type value_type;
    // The value.
    gguf_metadata_value_t value;
};

struct gguf_header_t {
    // Magic number to announce that this is a GGUF file.
    // Must be `GGUF` at the byte level: `0x47` `0x47` `0x55` `0x46`.
    // Your executor might do little-endian byte order, so it might be
    // check for 0x46554747 and letting the endianness cancel out.
    // Consider being *very* explicit about the byte order here.
    uint32_t magic;
    // The version of the format implemented.
    // Must be `3` for version described in this spec.
    uint32_t version;
    // The number of tensors in the file.
    // This is explicit, instead of being included in the metadata, to ensure
    // it is always present for loading the tensors.
    uint64_t tensor_count;
    // The number of metadata key-value pairs.
    uint64_t metadata_kv_count;
    // The metadata key-value pairs.
    gguf_metadata_kv_t metadata_kv[metadata_kv_count];
};

uint64_t align_offset(uint64_t offset) {
    return offset + (ALIGNMENT - (offset % ALIGNMENT)) % ALIGNMENT;
}

struct gguf_tensor_info_t {
    // The name of the tensor. It is a standard GGUF string, with the caveat that
    // it must be at most 64 bytes long.
    gguf_string_t name;
    // The number of dimensions in the tensor.
    // Currently at most 4, but this may change in the future.
    uint32_t n_dimensions;
    // The dimensions of the tensor.
    uint64_t dimensions[n_dimensions];
    // The type of the tensor.
    ggml_type type;
    // The offset of the tensor's data in this file in bytes.
    //
    // This offset is relative to `tensor_data`, not to the start
    // of the file, to make it easier for writers to write the file.
    // Readers should consider exposing this offset relative to the
    // file to make it easier to read the data.
    //
    // Must be a multiple of `ALIGNMENT`. That is, `align_offset(offset) == offset`.
    uint64_t offset;
};

struct gguf_file_t {
    // The header of the file.
    gguf_header_t header;

    // Tensor infos, which can be used to locate the tensor data.
    gguf_tensor_info_t tensor_infos[header.tensor_count];

    // Padding to the nearest multiple of `ALIGNMENT`.
    //
    // That is, if `sizeof(header) + sizeof(tensor_infos)` is not a multiple
    // of `ALIGNMENT`, this padding is added to make it so.
    //
    // This can be calculated as `align_offset(position) - position`, where
    // `position` is the position of the end of `tensor_infos`
    // (i.e. `sizeof(header) + sizeof(tensor_infos)`).
    uint8_t _padding[];

    // Tensor data.
    //
    // This is arbitrary binary data corresponding to the weights of the model.
    // Each tensor's data must be stored within this array, and located through
    // its `tensor_infos` entry. The offset of each tensor's data must be a
    // multiple of `ALIGNMENT`, and the space between tensors should be padded
    // to `ALIGNMENT` bytes.
    uint8_t tensor_data[];
};
```

## Standardized Key-Value Pairs

### General

#### Required

- **`general.architecture: string`**: describes what architecture this model implements.
  All lowercase ASCII, with only `[a-z0-9]+` characters allowed.
  Known values include: `llama`, `mpt`, `gptneox`, `gptj`, `gpt2`, `bloom`, `falcon`, `mamba`, `rwkv`
- **`general.quantization_version: uint32`**: The version of the quantization format.
  Not required if the model is not quantized. If any tensors are quantized, this _must_ be present.
- **`general.alignment: uint32`**: the global alignment to use, as described above.
  This can vary to allow for different alignment schemes, but it must be a multiple of 8.
  Some writers may not write the alignment. If the alignment is **not** specified, assume it is `32`.

#### General metadata

- `general.name: string`: The name of the model.
- `general.file_type: uint32`: An enumerated value describing the type of the majority of the tensors in the file.
  - `ALL_F32 = 0`
  - `MOSTLY_F16 = 1`
  - `MOSTLY_Q4_0 = 2`
  - `MOSTLY_Q4_1 = 3`
  - `MOSTLY_Q8_0 = 7`
  - `MOSTLY_Q5_0 = 8`
  - `MOSTLY_Q5_1 = 9`
  - `MOSTLY_Q2_K = 10`
  - `MOSTLY_Q3_K_S = 11`
  - `MOSTLY_Q3_K_M = 12`
  - `MOSTLY_Q3_K_L = 13`
  - `MOSTLY_Q4_K_S = 14`
  - `MOSTLY_Q4_K_M = 15`
  - `MOSTLY_Q5_K_S = 16`
  - `MOSTLY_Q5_K_M = 17`
  - `MOSTLY_Q6_K = 18`

### LLM Architecture Keys

In the following, `[llm]` is used to fill in for the name of a specific LLM architecture.
For example, `llama` for LLaMA.

- `[llm].context_length: uint64`: length of the context (in tokens) that the model was trained on.
- `[llm].embedding_length: uint64`: Embedding layer size.
- `[llm].block_count: uint64`: The number of blocks of attention+feed-forward layers.
- `[llm].feed_forward_length: uint64`: The length of the feed-forward layer.
- `[llm].expert_count: uint32`: Number of experts in MoE models.
- `[llm].expert_used_count: uint32`: Number of experts used during each token evaluation.

#### Attention

- `[llm].attention.head_count: uint64`: Number of attention heads.
- `[llm].attention.head_count_kv: uint64`: The number of heads per group used in Grouped-Query-Attention.
- `[llm].attention.layer_norm_rms_epsilon: float32`: Layer RMS normalization epsilon.
- `[llm].attention.key_length: uint32`: The optional size of a key head.
- `[llm].attention.value_length: uint32`: The optional size of a value head.

#### RoPE

- `[llm].rope.dimension_count: uint64`: The number of rotary dimensions for RoPE.
- `[llm].rope.freq_base: float32`: The base frequency for RoPE.

### Tokenizer

#### GGML Tokenizer

- `tokenizer.ggml.model: string`: The name of the tokenizer model.
  Known values: `llama`, `replit`, `gpt2`, `rwkv`
- `tokenizer.ggml.tokens: array[string]`: A list of tokens indexed by the token ID.
- `tokenizer.ggml.scores: array[float32]`: If present, the score/probability of each token.
  Must have the same length and index as `tokens`.
- `tokenizer.ggml.token_type: array[int32]`: The token type
  (1=normal, 2=unknown, 3=control, 4=user defined, 5=unused, 6=byte).
  Must have the same length and index as `tokens`.
- `tokenizer.ggml.merges: array[string]`: If present, the merges of the tokenizer.
- `tokenizer.ggml.added_tokens: array[string]`: If present, tokens added after training.

##### Special tokens

- `tokenizer.ggml.bos_token_id: uint32`: Beginning of sequence marker
- `tokenizer.ggml.eos_token_id: uint32`: End of sequence marker
- `tokenizer.ggml.unknown_token_id: uint32`: Unknown token
- `tokenizer.ggml.separator_token_id: uint32`: Separator token
- `tokenizer.ggml.padding_token_id: uint32`: Padding token

## Standardized Tensor Names

### Base layers

`AA.weight` `AA.bias`

where `AA` can be:

- `token_embd`: Token embedding layer
- `pos_embd`: Position embedding layer
- `output_norm`: Output normalization layer
- `output`: Output layer

### Attention and feed-forward layer blocks

`blk.N.BB.weight` `blk.N.BB.bias`

where N signifies the block number a layer belongs to, and where `BB` could be:

- `attn_norm`: Attention normalization layer
- `attn_q`: Attention query layer
- `attn_k`: Attention key layer
- `attn_v`: Attention value layer
- `attn_output`: Attention output layer
- `ffn_norm`: Feed-forward network normalization layer
- `ffn_up`: Feed-forward network "up" layer
- `ffn_gate`: Feed-forward network "gate" layer
- `ffn_down`: Feed-forward network "down" layer

## Tensor Type Sizes

For unquantized types, the byte size per element is:

- `GGML_TYPE_F32 (0)`: 4 bytes per element (IEEE 754 single-precision)
- `GGML_TYPE_F16 (1)`: 2 bytes per element (IEEE 754 half-precision)
- `GGML_TYPE_F64 (28)`: 8 bytes per element (IEEE 754 double-precision)
- `GGML_TYPE_I8 (24)`: 1 byte per element
- `GGML_TYPE_I16 (25)`: 2 bytes per element
- `GGML_TYPE_I32 (26)`: 4 bytes per element
- `GGML_TYPE_I64 (27)`: 8 bytes per element

## LLaMA Required Metadata

For a LLaMA architecture model, the following metadata keys are required:

- `llama.context_length`
- `llama.embedding_length`
- `llama.block_count`
- `llama.feed_forward_length`
- `llama.rope.dimension_count`
- `llama.attention.head_count`
- `llama.attention.layer_norm_rms_epsilon`

Optional:

- `llama.rope.freq_base`
- `llama.attention.head_count_kv`
- `llama.expert_count`
- `llama.expert_used_count`
