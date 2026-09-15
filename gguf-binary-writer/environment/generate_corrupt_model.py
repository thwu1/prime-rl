#!/usr/bin/env python3
"""Generate a GGUF v3 file with deliberate binary corruptions for forensic analysis.
This script is run at Docker build time and then deleted."""
import struct


def encode_string(s):
    """Encode a GGUF string: uint64 length + UTF-8 bytes."""
    raw = s.encode('utf-8')
    return struct.pack('<Q', len(raw)) + raw


def encode_kv_scalar(key, type_id, value):
    """Encode a scalar metadata KV pair."""
    buf = encode_string(key)
    buf += struct.pack('<I', type_id)
    if type_id == 8:  # STRING
        buf += encode_string(value)
    elif type_id == 4:  # UINT32
        buf += struct.pack('<I', value)
    elif type_id == 10:  # UINT64
        buf += struct.pack('<Q', value)
    elif type_id == 6:  # FLOAT32
        buf += struct.pack('<f', value)
    return buf


def encode_kv_array(key, elem_type_id, values):
    """Encode an array metadata KV pair."""
    buf = encode_string(key)
    buf += struct.pack('<I', 9)  # ARRAY type tag
    buf += struct.pack('<I', elem_type_id)
    buf += struct.pack('<Q', len(values))
    for v in values:
        if elem_type_id == 8:  # STRING
            buf += encode_string(v)
        elif elem_type_id == 6:  # FLOAT32
            buf += struct.pack('<f', v)
        elif elem_type_id == 5:  # INT32
            buf += struct.pack('<i', v)
    return buf


def align_up(offset, alignment=32):
    r = offset % alignment
    return offset if r == 0 else offset + (alignment - r)


def make_tensor_data(type_id, dimensions, fill_value):
    """Generate uniform tensor data bytes using struct (no numpy needed)."""
    n_elements = 1
    for d in dimensions:
        n_elements *= d
    if type_id == 0:  # F32
        single = struct.pack('<f', fill_value)
    elif type_id == 1:  # F16
        single = struct.pack('<e', fill_value)
    else:
        raise ValueError(f"Unsupported tensor type: {type_id}")
    return single * n_elements


def main():
    ALIGNMENT = 32

    # ===== METADATA (20 entries) =====
    metadata_buf = b''

    scalar_entries = [
        ("general.architecture", 8, "llama"),
        ("general.name", 8, "TestModel-Bench"),
        ("general.quantization_version", 4, 2),
        ("general.alignment", 4, 32),
        ("general.file_type", 4, 1),
        ("llama.context_length", 10, 4096),
        ("llama.embedding_length", 10, 256),
        ("llama.block_count", 10, 4),
        ("llama.feed_forward_length", 10, 512),
        ("llama.attention.head_count", 10, 8),
        ("llama.attention.head_count_kv", 10, 4),
        ("llama.attention.layer_norm_rms_epsilon", 6, 1e-5),
        ("llama.rope.dimension_count", 10, 32),
        ("llama.rope.freq_base", 6, 10000.0),
        ("tokenizer.ggml.model", 8, "llama"),
    ]
    for key, tid, val in scalar_entries:
        metadata_buf += encode_kv_scalar(key, tid, val)

    # Array entries
    metadata_buf += encode_kv_array(
        "tokenizer.ggml.tokens", 8,
        ["<pad>", "<eos>", "<bos>", "hello", "world"])
    metadata_buf += encode_kv_array(
        "tokenizer.ggml.scores", 6,
        [0.0, 0.0, 0.0, -1.0, -2.0])
    metadata_buf += encode_kv_array(
        "tokenizer.ggml.token_type", 5,
        [3, 3, 3, 1, 1])

    # Final scalar entries
    metadata_buf += encode_kv_scalar("tokenizer.ggml.bos_token_id", 4, 2)
    metadata_buf += encode_kv_scalar("tokenizer.ggml.eos_token_id", 4, 1)

    METADATA_COUNT = 20  # 15 scalar + 3 array + 2 scalar

    # ===== TENSORS (6 entries) =====
    tensor_specs = [
        ("token_embd.weight",       [256, 5],   0, 0.01),   # F32
        ("blk.0.attn_norm.weight",  [256],      0, 1.0),    # F32
        ("blk.0.attn_q.weight",     [256, 256], 1, 0.02),   # F16
        ("blk.0.attn_k.weight",     [128, 256], 1, 0.03),   # F16
        ("blk.0.ffn_up.weight",     [512, 256], 1, 0.04),   # F16
        ("output_norm.weight",      [256],      0, 1.0),    # F32
    ]
    TENSOR_COUNT = len(tensor_specs)

    # Generate tensor data and compute aligned offsets
    tensor_data_parts = []
    tensor_offsets = []
    current_offset = 0
    for name, dims, type_id, fill in tensor_specs:
        data = make_tensor_data(type_id, dims, fill)
        tensor_offsets.append(current_offset)
        tensor_data_parts.append(data)
        current_offset = align_up(current_offset + len(data), ALIGNMENT)

    # Encode tensor info entries
    tensor_info_buf = b''
    for i, (name, dims, type_id, fill) in enumerate(tensor_specs):
        tensor_info_buf += encode_string(name)
        tensor_info_buf += struct.pack('<I', len(dims))
        for d in dims:
            tensor_info_buf += struct.pack('<Q', d)
        tensor_info_buf += struct.pack('<I', type_id)
        tensor_info_buf += struct.pack('<Q', tensor_offsets[i])

    # ===== HEADER =====
    header = struct.pack('<I', 0x46554747)  # GGUF magic
    header += struct.pack('<I', 3)           # version
    header += struct.pack('<Q', TENSOR_COUNT)
    header += struct.pack('<Q', METADATA_COUNT)

    # ===== ALIGNMENT PADDING =====
    pre_data_size = len(header) + len(metadata_buf) + len(tensor_info_buf)
    tensor_data_start = align_up(pre_data_size, ALIGNMENT)
    padding_size = tensor_data_start - pre_data_size

    # ===== ASSEMBLE FILE =====
    file_data = bytearray()
    file_data += header
    file_data += metadata_buf
    file_data += tensor_info_buf
    file_data += b'\x00' * padding_size

    for i, data in enumerate(tensor_data_parts):
        file_data += data
        if i < len(tensor_data_parts) - 1:
            next_off = tensor_offsets[i + 1]
            curr_end = tensor_offsets[i] + len(data)
            inter_pad = next_off - curr_end
            if inter_pad > 0:
                file_data += b'\x00' * inter_pad

    # ===== APPLY 5 BINARY CORRUPTIONS =====

    # Corruption 1: Magic number — change byte 3 from 0x46 ('F') to 0x47 ('G')
    # Makes magic read as "GGUG" instead of "GGUF"
    file_data[3] = 0x47

    # Corruption 2: Version — change from 3 to 2
    struct.pack_into('<I', file_data, 4, 2)

    # Corruption 3: Metadata KV count — inflate from 20 to 22
    struct.pack_into('<Q', file_data, 16, 22)

    # Corruption 4: Tensor count — inflate from 6 to 8
    struct.pack_into('<Q', file_data, 8, 8)

    # Corruption 5: XOR 128 bytes of tensor #2 (blk.0.attn_q.weight) data
    # Start 256 bytes into the tensor (element index 128 for F16)
    xor_start = tensor_data_start + tensor_offsets[2] + 256
    for j in range(128):
        file_data[xor_start + j] ^= 0xFF

    # ===== WRITE =====
    with open('/app/model.gguf', 'wb') as f:
        f.write(file_data)

    print(f"Generated corrupted GGUF: {len(file_data)} bytes")
    print(f"  Tensor data starts at offset: {tensor_data_start}")
    print(f"  5 corruptions applied")


if __name__ == '__main__':
    main()
