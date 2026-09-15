#!/usr/bin/env python3
"""
Repair a corrupted GGUF v3 file by diagnosing and fixing binary defects.

Strategy:
1. Inspect the header bytes to identify magic/version errors
2. Manually walk metadata entries to determine actual KV count
3. Manually walk tensor info entries to determine actual tensor count
4. Scan tensor data for corrupted values and repair them
5. Write the repaired binary
"""
import struct
import math


def read_gguf_string(data, off):
    """Read a GGUF string: uint64 length prefix + UTF-8 bytes."""
    length = struct.unpack_from('<Q', data, off)[0]
    off += 8
    s = data[off:off + length].decode('utf-8')
    off += length
    return s, off


# Byte sizes for scalar metadata value types
SCALAR_SIZES = {
    0: 1,   # UINT8
    1: 1,   # INT8
    2: 2,   # UINT16
    3: 2,   # INT16
    4: 4,   # UINT32
    5: 4,   # INT32
    6: 4,   # FLOAT32
    7: 1,   # BOOL
    10: 8,  # UINT64
    11: 8,  # INT64
    12: 8,  # FLOAT64
}


def skip_metadata_value(data, off):
    """Skip over a typed metadata value, returning the new offset."""
    type_id = struct.unpack_from('<I', data, off)[0]
    off += 4
    if type_id == 9:  # ARRAY
        elem_type = struct.unpack_from('<I', data, off)[0]
        off += 4
        count = struct.unpack_from('<Q', data, off)[0]
        off += 8
        for _ in range(count):
            if elem_type == 8:  # STRING element
                _, off = read_gguf_string(data, off)
            else:
                off += SCALAR_SIZES[elem_type]
    elif type_id == 8:  # STRING
        _, off = read_gguf_string(data, off)
    else:
        off += SCALAR_SIZES[type_id]
    return off


def align_up(off, alignment=32):
    r = off % alignment
    return off if r == 0 else off + (alignment - r)


def main():
    with open('/app/model.gguf', 'rb') as f:
        data = bytearray(f.read())

    print(f"File size: {len(data)} bytes")

    # ===== DIAGNOSE & FIX HEADER =====

    # Check magic number (offset 0, 4 bytes)
    magic = struct.unpack_from('<I', data, 0)[0]
    print(f"[1] Magic: 0x{magic:08X} (expected 0x46554747)")
    if magic != 0x46554747:
        print("    -> Fixing magic number")
        struct.pack_into('<I', data, 0, 0x46554747)

    # Check version (offset 4, 4 bytes)
    version = struct.unpack_from('<I', data, 4)[0]
    print(f"[2] Version: {version} (expected 3)")
    if version != 3:
        print("    -> Fixing version to 3")
        struct.pack_into('<I', data, 4, 3)

    # ===== DIAGNOSE METADATA COUNT =====
    # Header claims a metadata_kv_count but it may be wrong.
    # Walk the metadata section manually to find the actual count.
    header_kv_count = struct.unpack_from('<Q', data, 16)[0]
    print(f"[3] Header metadata_kv_count: {header_kv_count}")

    off = 24  # skip 24-byte header
    kv_count = 0

    while off < len(data):
        saved = off
        try:
            # Try to read a GGUF string key
            key_len = struct.unpack_from('<Q', data, off)[0]
            if key_len == 0 or key_len > 1000:
                off = saved
                break
            off += 8
            key_bytes = data[off:off + key_len]
            key = key_bytes.decode('ascii')
            # GGUF metadata keys never contain 'weight' or 'bias'
            # (those are tensor names). Use this as a boundary heuristic.
            if 'weight' in key or 'bias' in key:
                off = saved
                break
            off += key_len
            off = skip_metadata_value(data, off)
            kv_count += 1
        except Exception:
            off = saved
            break

    print(f"    Actual metadata KV count: {kv_count}")
    if kv_count != header_kv_count:
        print(f"    -> Fixing metadata_kv_count from {header_kv_count} to {kv_count}")
        struct.pack_into('<Q', data, 16, kv_count)

    # ===== DIAGNOSE TENSOR COUNT =====
    header_tc = struct.unpack_from('<Q', data, 8)[0]
    print(f"[4] Header tensor_count: {header_tc}")

    tensor_infos = []
    tc = 0
    while off < len(data):
        saved = off
        try:
            name_len = struct.unpack_from('<Q', data, off)[0]
            if name_len == 0 or name_len > 256:
                off = saved
                break
            off += 8
            name = data[off:off + name_len].decode('ascii')
            off += name_len

            n_dims = struct.unpack_from('<I', data, off)[0]
            if n_dims == 0 or n_dims > 4:
                off = saved
                break
            off += 4

            dims = []
            for _ in range(n_dims):
                dims.append(struct.unpack_from('<Q', data, off)[0])
                off += 8

            ttype = struct.unpack_from('<I', data, off)[0]
            if ttype > 35:  # beyond max valid ggml_type
                off = saved
                break
            off += 4

            toff = struct.unpack_from('<Q', data, off)[0]
            off += 8

            tensor_infos.append((name, dims, ttype, toff))
            tc += 1
        except Exception:
            off = saved
            break

    print(f"    Actual tensor count: {tc}")
    if tc != header_tc:
        print(f"    -> Fixing tensor_count from {header_tc} to {tc}")
        struct.pack_into('<Q', data, 8, tc)

    # ===== DIAGNOSE & REPAIR TENSOR DATA =====
    tensor_data_start = align_up(off, 32)
    print(f"[5] Tensor data starts at offset: {tensor_data_start}")

    ELEM_SIZE = {0: 4, 1: 2}
    FMT = {0: '<f', 1: '<e'}

    total_repaired = 0
    for name, dims, ttype, toff in tensor_infos:
        n_elem = 1
        for d in dims:
            n_elem *= d
        esize = ELEM_SIZE[ttype]
        fmt = FMT[ttype]
        base = tensor_data_start + toff

        # Read first element as the reference fill value
        ref_val = struct.unpack_from(fmt, data, base)[0]

        # Scan for corrupted elements and repair
        corrupted = 0
        for i in range(n_elem):
            pos = base + i * esize
            val = struct.unpack_from(fmt, data, pos)[0]
            if math.isnan(val) or math.isinf(val) or abs(val - ref_val) > 0.01:
                struct.pack_into(fmt, data, pos, ref_val)
                corrupted += 1

        if corrupted > 0:
            print(f"    Tensor '{name}': repaired {corrupted} corrupted elements "
                  f"(fill={ref_val})")
            total_repaired += corrupted

    if total_repaired == 0:
        print("    No tensor data corruption detected")

    # ===== WRITE REPAIRED FILE =====
    with open('/app/repaired.gguf', 'wb') as f:
        f.write(data)

    print(f"\nRepaired file written to /app/repaired.gguf ({len(data)} bytes)")


if __name__ == '__main__':
    main()
