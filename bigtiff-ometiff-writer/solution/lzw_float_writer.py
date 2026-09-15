#!/usr/bin/env python3

"""
BigTIFF writer with LZW compression and floating-point predictor.
Uses only struct, numpy, hashlib, json, and Python standard library.
No TIFF I/O or LZW compression libraries.
"""

import hashlib
import json
import struct
import sys
import numpy as np

# ── TIFF constants ──────────────────────────────────────────────────────────

TYPE_SHORT = 3       # 2-byte unsigned integer
TYPE_LONG = 4        # 4-byte unsigned integer
TYPE_LONG8 = 16      # 8-byte unsigned integer (BigTIFF)

TAG_IMAGE_WIDTH = 256
TAG_IMAGE_LENGTH = 257
TAG_BITS_PER_SAMPLE = 258
TAG_COMPRESSION = 259
TAG_PHOTOMETRIC = 262
TAG_SAMPLES_PER_PIXEL = 277
TAG_PREDICTOR = 317
TAG_TILE_WIDTH = 322
TAG_TILE_LENGTH = 323
TAG_TILE_OFFSETS = 324
TAG_TILE_BYTE_COUNTS = 325
TAG_SAMPLE_FORMAT = 339


# ── Floating-point predictor (Predictor=3) ──────────────────────────────────

def float_predictor_encode_tile(tile):
    """
    Apply TIFF floating-point predictor to a 2D float32 tile.

    Per TIFF Technical Note 3, for each row:
    1. Byte-reorder: group bytes by position across all samples,
       MSB byte-plane first (byte 3, byte 2, byte 1, byte 0 for float32).
    2. Horizontal byte differencing on the reordered stream:
       out[0] = in[0]; out[i] = (in[i] - in[i-1]) mod 256
    """
    height, width = tile.shape
    bytes_per_sample = 4  # float32
    row_len = width * bytes_per_sample
    result = bytearray(height * row_len)

    for y in range(height):
        row_bytes = tile[y].astype('<f4').tobytes()
        src = np.frombuffer(row_bytes, dtype=np.uint8)

        # Byte-plane reorder: (width, 4) → transpose → reverse planes → flatten
        # MSB plane first: byte3 of all samples, then byte2, byte1, byte0
        reordered = src.reshape(width, bytes_per_sample).T[::-1].ravel().copy()

        # Horizontal byte differencing
        diff = np.empty_like(reordered)
        diff[0] = reordered[0]
        diff[1:] = np.subtract(reordered[1:].astype(np.int16),
                               reordered[:-1].astype(np.int16)) & 0xFF

        offset = y * row_len
        result[offset:offset + row_len] = diff.tobytes()

    return bytes(result)


# ── LZW encoder (TIFF variant, MSB-first, early change) ────────────────────

def lzw_encode(data):
    """
    Encode a bytes-like object using TIFF LZW compression.

    - MSB-first (big-endian) code packing
    - Starting code size: 9 bits
    - Clear code: 256, EOI code: 257
    - Early change: code size increases when next_code reaches 2^code_size
    - Table reset (clear code emitted) when table reaches 4096 entries
    """
    CLEAR = 256
    EOI = 257
    MAX_BITS = 12
    MAX_TABLE = 1 << MAX_BITS  # 4096

    # State
    table = {}
    next_code = 0
    code_size = 0

    # Bit-packing buffer (MSB-first)
    bit_buf = 0
    bits_pending = 0
    output = bytearray()

    def reset_table():
        nonlocal table, next_code, code_size
        table.clear()
        for i in range(256):
            table[bytes([i])] = i
        next_code = 258
        code_size = 9

    def emit(code):
        nonlocal bit_buf, bits_pending
        bit_buf = (bit_buf << code_size) | code
        bits_pending += code_size
        while bits_pending >= 8:
            bits_pending -= 8
            output.append((bit_buf >> bits_pending) & 0xFF)
        # Keep only valid bits to prevent unbounded growth
        if bits_pending > 0:
            bit_buf &= (1 << bits_pending) - 1
        else:
            bit_buf = 0

    reset_table()
    emit(CLEAR)

    if len(data) == 0:
        emit(EOI)
        if bits_pending > 0:
            output.append((bit_buf << (8 - bits_pending)) & 0xFF)
        return bytes(output)

    w = bytes([data[0]])

    for i in range(1, len(data)):
        c_byte = data[i]
        wc = w + bytes([c_byte])

        if wc in table:
            w = wc
        else:
            emit(table[w])

            if next_code < MAX_TABLE:
                table[wc] = next_code
                next_code += 1
                # Early change: increase code size when next_code hits 2^code_size
                if next_code == (1 << code_size) and code_size < MAX_BITS:
                    code_size += 1
            else:
                # Table full → emit clear code and reset
                emit(CLEAR)
                reset_table()

            w = bytes([c_byte])

    # Flush remaining match
    emit(table[w])
    emit(EOI)

    # Flush remaining bits (pad with zeros on the right)
    if bits_pending > 0:
        output.append((bit_buf << (8 - bits_pending)) & 0xFF)

    return bytes(output)


# ── BigTIFF writer ──────────────────────────────────────────────────────────

def ceil_div(a, b):
    return -(-a // b)


def write_bigtiff(output_path, data):
    """Write a BigTIFF file with LZW + floating-point predictor."""
    T, Z, Y, X = data.shape
    tile_w, tile_h = 64, 64
    tiles_x = ceil_div(X, tile_w)
    tiles_y = ceil_div(Y, tile_h)
    n_tiles = tiles_x * tiles_y          # per page
    num_pages = T * Z

    # ── Compress all tiles, tracking metrics ────────────────────────────
    compressed_tiles = []
    all_predicted_bytes = bytearray()
    page_compressed_sizes = [0] * num_pages

    for page_idx in range(num_pages):
        t = page_idx // Z
        z = page_idx % Z
        page = data[t, z]  # (Y, X) float32

        for ty in range(tiles_y):
            for tx in range(tiles_x):
                y0 = ty * tile_h
                x0 = tx * tile_w
                y1 = min(y0 + tile_h, Y)
                x1 = min(x0 + tile_w, X)

                tile = np.zeros((tile_h, tile_w), dtype=np.float32)
                tile[:y1 - y0, :x1 - x0] = page[y0:y1, x0:x1]

                predicted = float_predictor_encode_tile(tile)
                all_predicted_bytes.extend(predicted)

                compressed = lzw_encode(predicted)
                compressed_tiles.append(compressed)
                page_compressed_sizes[page_idx] += len(compressed)

    # Compute metrics for report
    predicted_sha256 = hashlib.sha256(bytes(all_predicted_bytes)).hexdigest()
    total_compressed = sum(page_compressed_sizes)

    # ── Write file ──────────────────────────────────────────────────────
    with open(output_path, 'wb') as f:
        # BigTIFF header (16 bytes)
        f.write(b'II')                          # little-endian
        f.write(struct.pack('<H', 43))           # BigTIFF magic
        f.write(struct.pack('<H', 8))            # offset size
        f.write(struct.pack('<H', 0))            # reserved
        first_ifd_pos = f.tell()
        f.write(struct.pack('<Q', 0))            # first IFD offset (placeholder)

        # Write compressed tile data
        tile_offsets = []
        tile_bytecounts = []
        for comp in compressed_tiles:
            tile_offsets.append(f.tell())
            f.write(comp)
            tile_bytecounts.append(len(comp))

        # Write external arrays: TileOffsets and TileByteCounts per page
        ext_offsets_pos = []
        ext_counts_pos = []
        for p in range(num_pages):
            base = p * n_tiles
            pos = f.tell()
            ext_offsets_pos.append(pos)
            for i in range(n_tiles):
                f.write(struct.pack('<Q', tile_offsets[base + i]))

            pos = f.tell()
            ext_counts_pos.append(pos)
            for i in range(n_tiles):
                f.write(struct.pack('<Q', tile_bytecounts[base + i]))

        # ── Write IFDs ──────────────────────────────────────────────────
        NUM_TAGS = 12
        IFD_SIZE = 8 + NUM_TAGS * 20 + 8  # count + entries + next_offset

        ifd_start = f.tell()
        ifd_positions = [ifd_start + i * IFD_SIZE for i in range(num_pages)]

        # Patch header
        f.seek(first_ifd_pos)
        f.write(struct.pack('<Q', ifd_positions[0]))
        f.seek(0, 2)

        for p in range(num_pages):
            entries = [
                (TAG_IMAGE_WIDTH,       TYPE_LONG,   1, X),
                (TAG_IMAGE_LENGTH,      TYPE_LONG,   1, Y),
                (TAG_BITS_PER_SAMPLE,   TYPE_SHORT,  1, 32),
                (TAG_COMPRESSION,       TYPE_SHORT,  1, 5),   # LZW
                (TAG_PHOTOMETRIC,       TYPE_SHORT,  1, 1),   # MinIsBlack
                (TAG_SAMPLES_PER_PIXEL, TYPE_SHORT,  1, 1),
                (TAG_PREDICTOR,         TYPE_SHORT,  1, 3),   # Floating point
                (TAG_TILE_WIDTH,        TYPE_LONG,   1, tile_w),
                (TAG_TILE_LENGTH,       TYPE_LONG,   1, tile_h),
                (TAG_TILE_OFFSETS,      TYPE_LONG8,  n_tiles, ext_offsets_pos[p]),
                (TAG_TILE_BYTE_COUNTS,  TYPE_LONG8,  n_tiles, ext_counts_pos[p]),
                (TAG_SAMPLE_FORMAT,     TYPE_SHORT,  1, 3),   # IEEEFP
            ]
            entries.sort(key=lambda e: e[0])

            next_ifd = ifd_positions[p + 1] if p < num_pages - 1 else 0

            # Write IFD header (entry count)
            f.write(struct.pack('<Q', len(entries)))
            # Write IFD entries
            for tag, dtype, count, val in entries:
                f.write(struct.pack('<HHQQ', tag, dtype, count, val))
            # Write next-IFD offset
            f.write(struct.pack('<Q', next_ifd))

    print(f'Wrote {output_path}: {num_pages} pages, {n_tiles} tiles/page')

    # ── Write metrics report ────────────────────────────────────────────
    report = {
        'predicted_data_sha256': predicted_sha256,
        'per_page_compressed_bytes': page_compressed_sizes,
        'total_compressed_bytes': total_compressed,
    }
    report_path = output_path.rsplit('.', 1)[0].rsplit('/', 1)[0] + '/report.json'
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)
    print(f'Wrote {report_path}')

    return report


# ── Main ────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    input_path = sys.argv[1]
    output_path = sys.argv[2]
    data = np.load(input_path)
    write_bigtiff(output_path, data)
