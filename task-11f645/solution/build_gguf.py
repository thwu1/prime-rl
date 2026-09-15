#!/usr/bin/env python3
"""Reference GGUF v3 binary writer.

Reads /app/model_spec.json and raw tensor data from /app/tensors/*.bin,
produces a valid GGUF v3 file at /app/output.gguf.

Implements the GGUF binary format from scratch using only the Python
standard library (no gguf package).
"""

import struct
import json
import os
import io

# ---- GGML type enum ----
GGML_TYPE_F32 = 0
GGML_TYPE_F16 = 1
GGML_TYPE_Q4_0 = 2

TYPE_STR_TO_ENUM = {
    "F32": GGML_TYPE_F32,
    "F16": GGML_TYPE_F16,
    "Q4_0": GGML_TYPE_Q4_0,
}

# ---- GGUF metadata value type enum ----
GGUF_TYPE_UINT32 = 4
GGUF_TYPE_FLOAT32 = 6
GGUF_TYPE_STRING = 8
GGUF_TYPE_ARRAY = 9
GGUF_TYPE_UINT64 = 10

META_TYPE_MAP = {
    "string": GGUF_TYPE_STRING,
    "uint32": GGUF_TYPE_UINT32,
    "uint64": GGUF_TYPE_UINT64,
    "float32": GGUF_TYPE_FLOAT32,
    "array": GGUF_TYPE_ARRAY,
}

ARRAY_ELEM_TYPE_MAP = {
    "string": GGUF_TYPE_STRING,
}

# Q4_0 block size
QK4_0 = 32


def align_offset(offset, alignment):
    """Return the next offset that is a multiple of alignment."""
    remainder = offset % alignment
    if remainder == 0:
        return offset
    return offset + (alignment - remainder)


def write_gguf_string(buf, s):
    """Write a GGUF string: uint64 length + UTF-8 bytes (no null terminator)."""
    encoded = s.encode('utf-8')
    buf.write(struct.pack('<Q', len(encoded)))
    buf.write(encoded)


def write_metadata_value(buf, value_type, value, spec_entry=None):
    """Write a typed metadata value."""
    if value_type == GGUF_TYPE_STRING:
        write_gguf_string(buf, value)
    elif value_type == GGUF_TYPE_UINT32:
        buf.write(struct.pack('<I', value))
    elif value_type == GGUF_TYPE_UINT64:
        buf.write(struct.pack('<Q', value))
    elif value_type == GGUF_TYPE_FLOAT32:
        buf.write(struct.pack('<f', value))
    elif value_type == GGUF_TYPE_ARRAY:
        array_type_str = spec_entry["array_type"]
        array_type = ARRAY_ELEM_TYPE_MAP[array_type_str]
        arr = value
        buf.write(struct.pack('<I', array_type))   # element type
        buf.write(struct.pack('<Q', len(arr)))      # element count
        for item in arr:
            write_metadata_value(buf, array_type, item)
    else:
        raise ValueError(f"Unsupported metadata type: {value_type}")


def write_metadata_kv(buf, entry):
    """Write a single metadata key-value pair."""
    write_gguf_string(buf, entry["key"])
    value_type = META_TYPE_MAP[entry["type"]]
    buf.write(struct.pack('<I', value_type))
    write_metadata_value(buf, value_type, entry["value"], entry)


def convert_f32_to_f16(raw_f32_bytes):
    """Convert raw float32 bytes to float16 bytes."""
    n = len(raw_f32_bytes) // 4
    result = bytearray()
    for i in range(n):
        val = struct.unpack('<f', raw_f32_bytes[i * 4:(i + 1) * 4])[0]
        result.extend(struct.pack('<e', val))
    return bytes(result)


def quantize_q4_0(raw_f32_bytes):
    """Quantize float32 data to Q4_0 format (ggml reference algorithm).

    Q4_0 block layout (18 bytes per 32 elements):
      - 2 bytes: FP16 scale factor (d)
      - 16 bytes: nibble-packed 4-bit quantized values

    Algorithm per block of 32 floats:
      1. Find the value with largest absolute value (max_val).
      2. Scale: d = max_val / -8
      3. Inverse scale: id = 1/d (or 0 if d == 0)
      4. For each pair (j, j+16) where j in [0..15]:
         - q_lo = clamp(int(input[j] * id + 8.5), 0, 15)
         - q_hi = clamp(int(input[j+16] * id + 8.5), 0, 15)
         - byte[j] = q_lo | (q_hi << 4)
    """
    n_floats = len(raw_f32_bytes) // 4
    if n_floats % QK4_0 != 0:
        raise ValueError(
            f"Element count ({n_floats}) must be a multiple of Q4_0 block size ({QK4_0})"
        )

    n_blocks = n_floats // QK4_0
    result = bytearray()

    for i in range(n_blocks):
        # Read 32 float32 values
        block_floats = []
        for j in range(QK4_0):
            idx = i * QK4_0 + j
            val = struct.unpack('<f', raw_f32_bytes[idx * 4:(idx + 1) * 4])[0]
            block_floats.append(val)

        # Find max absolute value (keeping original sign)
        amax = 0.0
        max_val = 0.0
        for v in block_floats:
            av = abs(v)
            if av > amax:
                amax = av
                max_val = v

        # Compute scale
        d = max_val / -8.0
        id_val = 1.0 / d if d != 0.0 else 0.0

        # Store scale as FP16
        result.extend(struct.pack('<e', d))

        # Quantize: interleave first half [0..15] and second half [16..31]
        half = QK4_0 // 2
        for j in range(half):
            x0 = block_floats[j] * id_val
            x1 = block_floats[j + half] * id_val

            xi0 = int(x0 + 8.5)
            xi1 = int(x1 + 8.5)

            # Clamp to [0, 15]
            xi0 = max(0, min(15, xi0))
            xi1 = max(0, min(15, xi1))

            result.append(xi0 | (xi1 << 4))

    return bytes(result)


def compute_tensor_data_size(n_elements, tensor_type):
    """Compute the byte size of tensor data for a given type."""
    if tensor_type == GGML_TYPE_F32:
        return n_elements * 4
    elif tensor_type == GGML_TYPE_F16:
        return n_elements * 2
    elif tensor_type == GGML_TYPE_Q4_0:
        return (n_elements // QK4_0) * 18
    else:
        raise ValueError(f"Unknown tensor type: {tensor_type}")


def main():
    # Load model specification
    with open('/app/model_spec.json', 'r') as f:
        spec = json.load(f)

    version = spec["version"]
    alignment = spec["alignment"]
    metadata_entries = spec["metadata"]
    tensor_specs = spec["tensors"]

    # Read and convert tensor data
    converted_data = []
    for tspec in tensor_specs:
        data_path = os.path.join('/app/tensors', tspec["data_file"])
        with open(data_path, 'rb') as f:
            raw = f.read()

        tensor_type = TYPE_STR_TO_ENUM[tspec["type"]]
        if tensor_type == GGML_TYPE_F32:
            converted = raw
        elif tensor_type == GGML_TYPE_F16:
            converted = convert_f32_to_f16(raw)
        elif tensor_type == GGML_TYPE_Q4_0:
            converted = quantize_q4_0(raw)
        else:
            raise ValueError(f"Unknown type: {tspec['type']}")

        converted_data.append(converted)

    # Compute tensor offsets (relative to tensor_data section start, aligned)
    tensor_offsets = []
    current_offset = 0
    for i, data in enumerate(converted_data):
        # Current tensor starts at current_offset (already aligned)
        tensor_offsets.append(current_offset)
        current_offset += len(data)
        # Align for next tensor (except after last)
        if i < len(converted_data) - 1:
            current_offset = align_offset(current_offset, alignment)

    # Build the GGUF file
    buf = io.BytesIO()

    # ---- GGUF Header (fixed fields) ----
    buf.write(b'GGUF')                                    # magic
    buf.write(struct.pack('<I', version))                  # version
    buf.write(struct.pack('<Q', len(tensor_specs)))        # tensor_count
    buf.write(struct.pack('<Q', len(metadata_entries)))    # metadata_kv_count

    # ---- Metadata KV pairs ----
    for entry in metadata_entries:
        write_metadata_kv(buf, entry)

    # ---- Tensor info entries ----
    for i, tspec in enumerate(tensor_specs):
        write_gguf_string(buf, tspec["name"])
        shape = tspec["shape"]
        buf.write(struct.pack('<I', len(shape)))           # n_dimensions
        for dim in shape:
            buf.write(struct.pack('<Q', dim))              # dimensions
        buf.write(struct.pack('<I', TYPE_STR_TO_ENUM[tspec["type"]]))  # type
        buf.write(struct.pack('<Q', tensor_offsets[i]))    # offset

    # ---- Alignment padding ----
    header_end = buf.tell()
    padding_needed = (alignment - (header_end % alignment)) % alignment
    buf.write(b'\x00' * padding_needed)

    # ---- Tensor data ----
    for i, data in enumerate(converted_data):
        buf.write(data)
        # Pad between tensors (not after the last one)
        if i < len(converted_data) - 1:
            data_end_offset = tensor_offsets[i] + len(data)
            next_offset = tensor_offsets[i + 1]
            inter_padding = next_offset - data_end_offset
            if inter_padding > 0:
                buf.write(b'\x00' * inter_padding)

    # Write to file
    with open('/app/output.gguf', 'wb') as f:
        f.write(buf.getvalue())

    file_size = os.path.getsize('/app/output.gguf')
    print(f"Successfully wrote /app/output.gguf ({file_size} bytes)")


if __name__ == "__main__":
    main()
