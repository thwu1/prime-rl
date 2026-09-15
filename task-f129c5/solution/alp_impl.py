#!/usr/bin/env python3
"""ALP (Adaptive Lossless floating-Point) compression implementation.

Implements the full ALP pipeline: exponent discovery via sampling,
encode/decode with IEEE 754 bitwise fidelity, frame-of-reference,
bit-packing, patch storage, and binary serialization.
"""

import struct
import math

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHUNK_SIZE = 1024
MAX_E = 18
I64_MAX = (1 << 63) - 1
I64_MIN = -(1 << 63)
MAGIC = b"ALP1"

# Precomputed lookup tables (as f64)
FACT = [10.0 ** e for e in range(MAX_E + 1)]
FRAC = [10.0 ** (-f) for f in range(MAX_E + 1)]


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def _bitwise_equal(a, b):
    return struct.pack("<d", a) == struct.pack("<d", b)


def _try_encode(v, e, f):
    """Attempt to encode v with exponents (e, f).

    Returns (encoded_int, True) on success, (0, False) on failure.
    """
    if math.isnan(v) or math.isinf(v):
        return 0, False
    product = v * FACT[e]
    if not math.isfinite(product):
        return 0, False
    encoded = round(product)
    if encoded > I64_MAX or encoded < I64_MIN:
        return 0, False
    decoded = encoded * FRAC[f]
    if _bitwise_equal(v, decoded):
        return encoded, True
    return 0, False


def _find_best_exponents(values):
    """Find the optimal (e, f) pair by sampling."""
    candidates = [
        v for v in values
        if v is not None and not math.isnan(v) and not math.isinf(v)
    ]
    if not candidates:
        return 0, 0

    n = len(candidates)
    sample_count = min(32, n)
    if sample_count == n:
        sample = candidates
    else:
        step = n / sample_count
        sample = [candidates[int(i * step)] for i in range(sample_count)]

    best_e, best_f, best_exc = 0, 0, len(sample) + 1

    for e in range(MAX_E + 1):
        for f in range(e + 1):
            exc = sum(1 for v in sample if not _try_encode(v, e, f)[1])
            if exc < best_exc:
                best_exc = exc
                best_e, best_f = e, f

    return best_e, best_f


# ---------------------------------------------------------------------------
# Bit-packing
# ---------------------------------------------------------------------------

def _bitpack_encode(values, bit_width):
    if bit_width == 0 or not values:
        return b""
    total_bytes = (len(values) * bit_width + 7) // 8
    packed = bytearray(total_bytes)
    bit_pos = 0
    for v in values:
        for b in range(bit_width):
            if v & (1 << b):
                packed[bit_pos >> 3] |= 1 << (bit_pos & 7)
            bit_pos += 1
    return bytes(packed)


def _bitpack_decode(data, bit_width, count):
    if bit_width == 0:
        return [0] * count
    result = []
    bit_pos = 0
    for _ in range(count):
        v = 0
        for b in range(bit_width):
            if data[bit_pos >> 3] & (1 << (bit_pos & 7)):
                v |= 1 << b
            bit_pos += 1
        result.append(v)
    return result


# ---------------------------------------------------------------------------
# Compress
# ---------------------------------------------------------------------------

def alp_compress(values):
    """Compress a list of float/None values into ALP binary format."""
    num_values = len(values)

    if num_values == 0:
        buf = bytearray(32)
        buf[0:4] = MAGIC
        return bytes(buf)

    # 1. Find optimal exponents
    e, f = _find_best_exponents(values)

    # 2. Encode
    encoded = []
    patches = []
    null_indices = set()
    patch_indices = set()

    for i, v in enumerate(values):
        if v is None:
            null_indices.add(i)
            encoded.append(0)
            continue
        enc_val, ok = _try_encode(v, e, f)
        if ok:
            encoded.append(enc_val)
        else:
            patches.append((i, v))
            patch_indices.add(i)
            encoded.append(0)

    # 3. Frame-of-reference
    valid = [
        encoded[i] for i in range(num_values)
        if i not in null_indices and i not in patch_indices
    ]
    for_base = min(valid) if valid else 0

    for_adjusted = []
    for i in range(num_values):
        if i in null_indices or i in patch_indices:
            for_adjusted.append(0)
        else:
            for_adjusted.append(encoded[i] - for_base)

    # 4. Bit width
    max_val = max(for_adjusted) if for_adjusted else 0
    bit_width = max_val.bit_length() if max_val > 0 else 0

    # 5. Chunk offsets
    num_chunks = (num_values + CHUNK_SIZE - 1) // CHUNK_SIZE
    chunk_counts = [0] * num_chunks
    for idx, _ in patches:
        chunk_counts[idx // CHUNK_SIZE] += 1
    chunk_offsets = [0]
    for c in chunk_counts:
        chunk_offsets.append(chunk_offsets[-1] + c)

    # 6. Null bitmap
    has_nulls = len(null_indices) > 0
    bitmap_size = (num_values + 7) // 8 if has_nulls else 0
    null_bitmap = bytearray(bitmap_size)
    for i in null_indices:
        null_bitmap[i >> 3] |= 1 << (i & 7)

    # 7. Bit-pack
    packed = _bitpack_encode(for_adjusted, bit_width)

    # 8. Serialize
    buf = bytearray()

    # Header (32 bytes)
    buf.extend(MAGIC)                               # 4
    buf.extend(struct.pack("<Q", num_values))        # 8
    buf.append(e)                                    # 1
    buf.append(f)                                    # 1
    buf.append(bit_width)                            # 1
    buf.extend(struct.pack("<q", for_base))          # 8
    buf.extend(struct.pack("<I", len(patches)))      # 4
    buf.extend(struct.pack("<H", num_chunks))        # 2
    buf.append(1 if has_nulls else 0)                # 1
    buf.extend(b"\x00\x00")                          # 2

    # Null bitmap
    buf.extend(null_bitmap)

    # Bit-packed integers
    buf.extend(packed)

    # Patches (sorted by index)
    for idx, val in patches:
        buf.extend(struct.pack("<Q", idx))
        buf.extend(struct.pack("<d", val))

    # Chunk offsets
    for off in chunk_offsets:
        buf.extend(struct.pack("<I", off))

    return bytes(buf)


# ---------------------------------------------------------------------------
# Decompress
# ---------------------------------------------------------------------------

def alp_decompress(data):
    """Decompress ALP binary data back to list of float/None."""
    if len(data) < 32:
        raise ValueError("Data too short for ALP header")

    pos = 0

    # Header
    magic = data[pos:pos + 4]; pos += 4
    if magic != MAGIC:
        raise ValueError(f"Invalid magic: {magic!r}")

    num_values = struct.unpack("<Q", data[pos:pos + 8])[0]; pos += 8
    e = data[pos]; pos += 1
    f = data[pos]; pos += 1
    bit_width = data[pos]; pos += 1
    for_base = struct.unpack("<q", data[pos:pos + 8])[0]; pos += 8
    num_patches = struct.unpack("<I", data[pos:pos + 4])[0]; pos += 4
    _num_chunks = struct.unpack("<H", data[pos:pos + 2])[0]; pos += 2
    has_nulls = bool(data[pos] & 1); pos += 1
    pos += 2  # reserved

    if num_values == 0:
        return []

    # Null bitmap
    null_indices = set()
    if has_nulls:
        bm_size = (num_values + 7) // 8
        bitmap = data[pos:pos + bm_size]; pos += bm_size
        for i in range(num_values):
            if bitmap[i >> 3] & (1 << (i & 7)):
                null_indices.add(i)

    # Bit-packed integers
    packed_size = (num_values * bit_width + 7) // 8 if bit_width > 0 else 0
    packed_data = data[pos:pos + packed_size]; pos += packed_size
    for_adjusted = _bitpack_decode(packed_data, bit_width, num_values)

    # Patches
    patch_map = {}
    for _ in range(num_patches):
        idx = struct.unpack("<Q", data[pos:pos + 8])[0]; pos += 8
        val = struct.unpack("<d", data[pos:pos + 8])[0]; pos += 8
        patch_map[idx] = val

    # Reconstruct
    result = []
    for i in range(num_values):
        if i in null_indices:
            result.append(None)
        elif i in patch_map:
            result.append(patch_map[i])
        else:
            enc_int = for_adjusted[i] + for_base
            result.append(enc_int * FRAC[f])

    return result
