#!/usr/bin/env python3
"""
GGUF v3 binary file writer — implements the format from the specification.
Produces /app/output.gguf from the descriptor at /app/requirements.json.
"""
import struct
import json
import os
import numpy as np

# ---- GGUF magic ----
GGUF_MAGIC = 0x46554747  # "GGUF" as little-endian uint32: bytes 0x47 0x47 0x55 0x46

# ---- Metadata value type IDs per spec ----
GGUF_TYPE_UINT8   = 0
GGUF_TYPE_INT8    = 1
GGUF_TYPE_UINT16  = 2
GGUF_TYPE_INT16   = 3
GGUF_TYPE_UINT32  = 4
GGUF_TYPE_INT32   = 5
GGUF_TYPE_FLOAT32 = 6
GGUF_TYPE_BOOL    = 7
GGUF_TYPE_STRING  = 8
GGUF_TYPE_ARRAY   = 9
GGUF_TYPE_UINT64  = 10
GGUF_TYPE_INT64   = 11
GGUF_TYPE_FLOAT64 = 12

TYPE_NAME_TO_ID = {
    'uint8':   GGUF_TYPE_UINT8,
    'int8':    GGUF_TYPE_INT8,
    'uint16':  GGUF_TYPE_UINT16,
    'int16':   GGUF_TYPE_INT16,
    'uint32':  GGUF_TYPE_UINT32,
    'int32':   GGUF_TYPE_INT32,
    'float32': GGUF_TYPE_FLOAT32,
    'bool':    GGUF_TYPE_BOOL,
    'string':  GGUF_TYPE_STRING,
    'array':   GGUF_TYPE_ARRAY,
    'uint64':  GGUF_TYPE_UINT64,
    'int64':   GGUF_TYPE_INT64,
    'float64': GGUF_TYPE_FLOAT64,
}

# struct format strings for scalar types
SCALAR_FMT = {
    GGUF_TYPE_UINT8:   '<B',
    GGUF_TYPE_INT8:    '<b',
    GGUF_TYPE_UINT16:  '<H',
    GGUF_TYPE_INT16:   '<h',
    GGUF_TYPE_UINT32:  '<I',
    GGUF_TYPE_INT32:   '<i',
    GGUF_TYPE_FLOAT32: '<f',
    GGUF_TYPE_BOOL:    '<B',
    GGUF_TYPE_UINT64:  '<Q',
    GGUF_TYPE_INT64:   '<q',
    GGUF_TYPE_FLOAT64: '<d',
}

# Tensor type ID to numpy dtype
TENSOR_DTYPE = {
    0: np.float32,  # F32
    1: np.float16,  # F16
}


def align_offset(offset, alignment):
    """Round offset up to the next multiple of alignment."""
    remainder = offset % alignment
    if remainder == 0:
        return offset
    return offset + (alignment - remainder)


def encode_gguf_string(s):
    """Encode a GGUF string: uint64 length + UTF-8 bytes (no null terminator)."""
    raw = s.encode('utf-8')
    return struct.pack('<Q', len(raw)) + raw


def encode_scalar_value(type_id, value):
    """Encode a scalar metadata value (without its type tag)."""
    if type_id == GGUF_TYPE_STRING:
        return encode_gguf_string(value)
    elif type_id == GGUF_TYPE_BOOL:
        return struct.pack('<B', 1 if value else 0)
    else:
        return struct.pack(SCALAR_FMT[type_id], value)


def encode_metadata_kv(key, type_name, value, array_type_name=None):
    """Encode a complete metadata key-value entry:
    gguf_string_t key + uint32 value_type + value data."""
    buf = encode_gguf_string(key)

    if type_name == 'array':
        # Array: type_tag=ARRAY, then element_type, count, elements
        buf += struct.pack('<I', GGUF_TYPE_ARRAY)
        elem_type_id = TYPE_NAME_TO_ID[array_type_name]
        buf += struct.pack('<I', elem_type_id)
        buf += struct.pack('<Q', len(value))
        for elem in value:
            buf += encode_scalar_value(elem_type_id, elem)
    else:
        type_id = TYPE_NAME_TO_ID[type_name]
        buf += struct.pack('<I', type_id)
        buf += encode_scalar_value(type_id, value)

    return buf


def encode_tensor_info(name, dimensions, type_id, offset):
    """Encode a tensor info entry:
    gguf_string_t name + uint32 n_dims + uint64[] dims + uint32 type + uint64 offset."""
    buf = encode_gguf_string(name)
    buf += struct.pack('<I', len(dimensions))
    for d in dimensions:
        buf += struct.pack('<Q', d)
    buf += struct.pack('<I', type_id)
    buf += struct.pack('<Q', offset)
    return buf


def generate_tensor_data(dimensions, type_id, fill_value):
    """Generate tensor data as bytes, filled uniformly with fill_value."""
    n_elements = 1
    for d in dimensions:
        n_elements *= d
    dtype = TENSOR_DTYPE[type_id]
    return np.full(n_elements, fill_value, dtype=dtype).tobytes()


def main():
    with open('/app/requirements.json', 'r') as f:
        reqs = json.load(f)

    alignment = reqs['alignment']
    version = reqs['version']
    metadata_specs = reqs['metadata']
    tensor_specs = reqs['tensors']

    # --- Step 1: Encode all metadata KV pairs ---
    metadata_buf = b''
    metadata_count = 0
    for key, spec in metadata_specs.items():
        if spec['type'] == 'array':
            metadata_buf += encode_metadata_kv(
                key, 'array', spec['value'], spec['array_type']
            )
        else:
            metadata_buf += encode_metadata_kv(key, spec['type'], spec['value'])
        metadata_count += 1

    # --- Step 2: Compute tensor data sizes and aligned offsets ---
    tensor_data_parts = []
    tensor_offsets = []
    current_data_offset = 0

    for tspec in tensor_specs:
        data = generate_tensor_data(
            tspec['dimensions'], tspec['type_id'], tspec['fill_value']
        )
        tensor_offsets.append(current_data_offset)
        tensor_data_parts.append(data)
        current_data_offset = align_offset(
            current_data_offset + len(data), alignment
        )

    # --- Step 3: Encode tensor info entries ---
    tensor_info_buf = b''
    for i, tspec in enumerate(tensor_specs):
        tensor_info_buf += encode_tensor_info(
            tspec['name'], tspec['dimensions'],
            tspec['type_id'], tensor_offsets[i]
        )

    # --- Step 4: Build file header ---
    header = b''
    header += struct.pack('<I', GGUF_MAGIC)
    header += struct.pack('<I', version)
    header += struct.pack('<Q', len(tensor_specs))
    header += struct.pack('<Q', metadata_count)

    # --- Step 5: Compute alignment padding before tensor data ---
    pre_data_size = len(header) + len(metadata_buf) + len(tensor_info_buf)
    tensor_data_start = align_offset(pre_data_size, alignment)
    pre_data_padding = tensor_data_start - pre_data_size

    # --- Step 6: Write the complete file ---
    with open('/app/output.gguf', 'wb') as f:
        # Header (magic, version, tensor_count, metadata_kv_count)
        f.write(header)

        # Metadata key-value pairs
        f.write(metadata_buf)

        # Tensor info entries
        f.write(tensor_info_buf)

        # Alignment padding
        f.write(b'\x00' * pre_data_padding)

        # Tensor data with inter-tensor alignment padding
        for i, data in enumerate(tensor_data_parts):
            f.write(data)
            if i < len(tensor_data_parts) - 1:
                next_offset = tensor_offsets[i + 1]
                current_end = tensor_offsets[i] + len(data)
                padding = next_offset - current_end
                if padding > 0:
                    f.write(b'\x00' * padding)

    file_size = os.path.getsize('/app/output.gguf')
    print(f"Wrote /app/output.gguf ({file_size} bytes)")
    print(f"  GGUF v{version}, {metadata_count} metadata KVs, "
          f"{len(tensor_specs)} tensors")
    print(f"  Alignment: {alignment} bytes")
    print(f"  Tensor data starts at file offset: {tensor_data_start}")


if __name__ == '__main__':
    main()
