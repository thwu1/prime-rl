#!/usr/bin/env python3
"""Generate a corrupted GGUF v3 file for the forensic repair task.

Builds a structurally valid GGUF v3 binary with correct tensor data,
then introduces 5 structural corruptions that cause standard GGUF
parsers to fail or report incorrect results. The tensor data payload
remains intact — only the structural framing is corrupted.
"""

import struct
import os
import random
import io

random.seed(12345)
os.makedirs('/app', exist_ok=True)

# ---- Constants ----
GGML_TYPE_F32 = 0
GGML_TYPE_F16 = 1
GGML_TYPE_Q4_0 = 2

GGUF_TYPE_UINT32 = 4
GGUF_TYPE_FLOAT32 = 6
GGUF_TYPE_STRING = 8
GGUF_TYPE_ARRAY = 9
GGUF_TYPE_UINT64 = 10

QK4_0 = 32
ALIGNMENT = 64


def gen_float32_data(n):
    return [random.gauss(0, 1) for _ in range(n)]


def write_gguf_string(buf, s):
    encoded = s.encode('utf-8')
    buf.write(struct.pack('<Q', len(encoded)))
    buf.write(encoded)


def align_up(offset, alignment):
    r = offset % alignment
    return offset if r == 0 else offset + (alignment - r)


def to_f32_bytes(data):
    return b''.join(struct.pack('<f', v) for v in data)


def to_f16_bytes(data):
    return b''.join(struct.pack('<e', v) for v in data)


def to_q4_0_bytes(data):
    n = len(data)
    assert n % QK4_0 == 0
    result = bytearray()
    for i in range(n // QK4_0):
        block = data[i * QK4_0:(i + 1) * QK4_0]
        amax = 0.0
        max_val = 0.0
        for v in block:
            if abs(v) > amax:
                amax = abs(v)
                max_val = v
        d = max_val / -8.0
        id_val = 1.0 / d if d != 0.0 else 0.0
        result.extend(struct.pack('<e', d))
        half = QK4_0 // 2
        for j in range(half):
            x0 = block[j] * id_val
            x1 = block[j + half] * id_val
            xi0 = max(0, min(15, int(x0 + 8.5)))
            xi1 = max(0, min(15, int(x1 + 8.5)))
            result.append(xi0 | (xi1 << 4))
    return bytes(result)


# ---- Generate tensor data ----
token_embd_data = gen_float32_data(512)    # [32, 16] F32
attn_norm_data = gen_float32_data(16)       # [16] F16
ffn_down_data = gen_float32_data(1024)      # [64, 16] Q4_0
output_data = gen_float32_data(512)         # [32, 16] F32

token_embd_bytes = to_f32_bytes(token_embd_data)
attn_norm_bytes = to_f16_bytes(attn_norm_data)
ffn_down_bytes = to_q4_0_bytes(ffn_down_data)
output_bytes = to_f32_bytes(output_data)

tensor_data_list = [token_embd_bytes, attn_norm_bytes, ffn_down_bytes, output_bytes]

# Compute tensor offsets (relative to tensor data start, aligned)
tensor_offsets = []
current = 0
for i, td in enumerate(tensor_data_list):
    tensor_offsets.append(current)
    current += len(td)
    if i < len(tensor_data_list) - 1:
        current = align_up(current, ALIGNMENT)


# ---- Build correct GGUF v3 file ----
buf = io.BytesIO()

# Header fixed fields
buf.write(b'GGUF')                            # magic
version_off = buf.tell()
buf.write(struct.pack('<I', 3))               # version
buf.write(struct.pack('<Q', 4))               # tensor_count
kv_count_off = buf.tell()
buf.write(struct.pack('<Q', 14))              # metadata_kv_count

# Metadata KV pairs
metadata = [
    ("general.architecture", GGUF_TYPE_STRING, "llama"),
    ("general.name", GGUF_TYPE_STRING, "TinyTestModel"),
    ("general.alignment", GGUF_TYPE_UINT32, 64),
    ("general.quantization_version", GGUF_TYPE_UINT32, 2),
    ("general.file_type", GGUF_TYPE_UINT32, 2),
    ("llama.context_length", GGUF_TYPE_UINT64, 512),
    ("llama.embedding_length", GGUF_TYPE_UINT64, 16),
    ("llama.block_count", GGUF_TYPE_UINT64, 1),
    ("llama.feed_forward_length", GGUF_TYPE_UINT64, 32),
    ("llama.attention.head_count", GGUF_TYPE_UINT64, 2),
    ("llama.attention.layer_norm_rms_epsilon", GGUF_TYPE_FLOAT32, 1e-5),
    ("llama.rope.dimension_count", GGUF_TYPE_UINT64, 8),
    ("general.tags", GGUF_TYPE_ARRAY, ["test", "tiny", "benchmark"]),
    ("general.quantized_by", GGUF_TYPE_STRING, "local"),
]

ctx_len_type_off = None

for key, vtype, value in metadata:
    write_gguf_string(buf, key)
    if key == "llama.context_length":
        ctx_len_type_off = buf.tell()
    buf.write(struct.pack('<I', vtype))
    if vtype == GGUF_TYPE_STRING:
        write_gguf_string(buf, value)
    elif vtype == GGUF_TYPE_UINT32:
        buf.write(struct.pack('<I', value))
    elif vtype == GGUF_TYPE_UINT64:
        buf.write(struct.pack('<Q', value))
    elif vtype == GGUF_TYPE_FLOAT32:
        buf.write(struct.pack('<f', value))
    elif vtype == GGUF_TYPE_ARRAY:
        buf.write(struct.pack('<I', GGUF_TYPE_STRING))
        buf.write(struct.pack('<Q', len(value)))
        for s in value:
            write_gguf_string(buf, s)

# Tensor info entries
tensor_specs = [
    ("token_embd.weight", [32, 16], GGML_TYPE_F32),
    ("blk.0.attn_norm.weight", [16], GGML_TYPE_F16),
    ("blk.0.ffn_down.weight", [64, 16], GGML_TYPE_Q4_0),
    ("output.weight", [32, 16], GGML_TYPE_F32),
]

ffn_type_off = None

for i, (name, shape, ttype) in enumerate(tensor_specs):
    write_gguf_string(buf, name)
    buf.write(struct.pack('<I', len(shape)))
    for dim in shape:
        buf.write(struct.pack('<Q', dim))
    if name == "blk.0.ffn_down.weight":
        ffn_type_off = buf.tell()
    buf.write(struct.pack('<I', ttype))
    buf.write(struct.pack('<Q', tensor_offsets[i]))

# Alignment padding
header_end = buf.tell()
pad_needed = (ALIGNMENT - (header_end % ALIGNMENT)) % ALIGNMENT
pad_start = header_end
buf.write(b'\x00' * pad_needed)

# Tensor data
for i, td in enumerate(tensor_data_list):
    buf.write(td)
    if i < len(tensor_data_list) - 1:
        end = tensor_offsets[i] + len(td)
        nxt = tensor_offsets[i + 1]
        gap = nxt - end
        if gap > 0:
            buf.write(b'\x00' * gap)


# ---- Apply 5 structural corruptions ----
file_data = bytearray(buf.getvalue())

# Defect 1: Header version 3 -> 2
struct.pack_into('<I', file_data, version_off, 2)

# Defect 2: Header metadata_kv_count 14 -> 12
struct.pack_into('<Q', file_data, kv_count_off, 12)

# Defect 3: llama.context_length value type UINT64(10) -> UINT32(4)
# This causes the parser to read only 4 bytes for an 8-byte value,
# shifting all subsequent parsing by 4 bytes and triggering cascading failures
struct.pack_into('<I', file_data, ctx_len_type_off, GGUF_TYPE_UINT32)

# Defect 4: blk.0.ffn_down.weight tensor type Q4_0(2) -> Q2_K(10)
struct.pack_into('<I', file_data, ffn_type_off, 10)

# Defect 5: Alignment padding 0x00 -> 0xFF
for i in range(pad_start, pad_start + pad_needed):
    file_data[i] = 0xFF

with open('/app/model.gguf', 'wb') as f:
    f.write(file_data)

print(f"Task setup complete: /app/model.gguf ({len(file_data)} bytes)")
