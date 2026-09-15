#!/usr/bin/env python3

"""
Construct a valid BigTIFF file from raw binary operations.

Builds a 2-page BigTIFF containing:
  Page 0: 512x512 uint16 grayscale, tiled 256x256, DEFLATE + horizontal predictor
  Page 1: 256x256x3 uint8 RGB, single strip, uncompressed

Uses only struct, zlib, and numpy — no TIFF libraries.
"""

import struct
import zlib
import numpy as np

# ── TIFF data type codes and sizes ──────────────────────────────────────────

TIFF_SHORT = 3       # uint16, 2 bytes
TIFF_LONG = 4        # uint32, 4 bytes
TIFF_RATIONAL = 5    # 2 × uint32, 8 bytes
TIFF_LONG8 = 16      # uint64, 8 bytes

TYPE_SIZE = {
    TIFF_SHORT: 2,
    TIFF_LONG: 4,
    TIFF_RATIONAL: 8,
    TIFF_LONG8: 8,
}


def encode_values(dtype, values):
    """Pack a list of typed values into raw bytes."""
    if dtype == TIFF_SHORT:
        return struct.pack(f'<{len(values)}H', *values)
    elif dtype == TIFF_LONG:
        return struct.pack(f'<{len(values)}I', *values)
    elif dtype == TIFF_RATIONAL:
        parts = []
        for num, den in values:
            parts.append(struct.pack('<II', num, den))
        return b''.join(parts)
    elif dtype == TIFF_LONG8:
        return struct.pack(f'<{len(values)}Q', *values)
    raise ValueError(f'Unknown TIFF type {dtype}')


def apply_horizontal_predictor_u16(tile):
    """Apply TIFF horizontal differencing predictor (tag 317 = 2) to uint16 tile.

    For each row:
      filtered[col=0]   = original[col=0]
      filtered[col>0]   = (original[col] - original[col-1]) mod 65536

    This is reversed on read by cumulative summation.
    """
    filtered = np.empty_like(tile)
    filtered[:, 0] = tile[:, 0]
    # int32 arithmetic then cast back to uint16 gives correct modular wrapping
    filtered[:, 1:] = (
        tile[:, 1:].astype(np.int32) - tile[:, :-1].astype(np.int32)
    ).astype(np.uint16)
    return filtered


def write_ifd(buf, tag_defs):
    """Append a BigTIFF IFD to *buf*.

    tag_defs: sorted list of (code, dtype, count, raw_value_bytes)
        - If the total value size ≤ 8 bytes the value is stored inline.
        - Otherwise raw_value_bytes must already be an 8-byte packed offset.

    Returns the buffer position of the next-IFD-offset field so it can be
    patched later.
    """
    buf.extend(struct.pack('<Q', len(tag_defs)))          # entry count (uint64)

    for code, dtype, count, val_bytes in tag_defs:
        buf.extend(struct.pack('<H', code))               # tag code
        buf.extend(struct.pack('<H', dtype))              # data type
        buf.extend(struct.pack('<Q', count))              # count
        total = TYPE_SIZE[dtype] * count
        if total <= 8:
            buf.extend(val_bytes.ljust(8, b'\x00'))       # inline value
        else:
            buf.extend(val_bytes.ljust(8, b'\x00'))       # external offset
    next_ifd_pos = len(buf)
    buf.extend(struct.pack('<Q', 0))                      # next IFD offset
    return next_ifd_pos


def main():
    output_path = '/app/output.tif'

    # ── Generate image data ─────────────────────────────────────────────────

    # Page 0: 512×512 uint16 grayscale
    W0, H0 = 512, 512
    y0, x0 = np.mgrid[0:H0, 0:W0]
    img0 = ((y0.astype(np.int64) * W0 + x0.astype(np.int64)) % 65536).astype(
        np.uint16
    )

    # Page 1: 256×256×3 uint8 RGB
    W1, H1 = 256, 256
    y1, x1 = np.mgrid[0:H1, 0:W1]
    img1 = np.stack(
        [
            (y1 % 256).astype(np.uint8),
            (x1 % 256).astype(np.uint8),
            ((y1 + x1) % 256).astype(np.uint8),
        ],
        axis=-1,
    )

    # ── Build file buffer ───────────────────────────────────────────────────

    buf = bytearray()

    # BigTIFF header — 16 bytes
    buf.extend(b'II')                         # byte-order: little-endian
    buf.extend(struct.pack('<H', 43))         # version: BigTIFF
    buf.extend(struct.pack('<H', 8))          # offset byte-size
    buf.extend(struct.pack('<H', 0))          # reserved (always 0)
    first_ifd_pos = len(buf)
    buf.extend(struct.pack('<Q', 0))          # first IFD offset (placeholder)
    assert len(buf) == 16

    # ── Page 0 tile data ────────────────────────────────────────────────────

    TILE_W, TILE_H = 256, 256
    tiles_across = W0 // TILE_W   # 2
    tiles_down = H0 // TILE_H     # 2
    n_tiles = tiles_across * tiles_down  # 4

    tile_offsets = []
    tile_bytecounts = []

    for ty in range(tiles_down):
        for tx in range(tiles_across):
            tile = img0[
                ty * TILE_H : (ty + 1) * TILE_H,
                tx * TILE_W : (tx + 1) * TILE_W,
            ]
            filtered = apply_horizontal_predictor_u16(tile)
            compressed = zlib.compress(filtered.tobytes())
            tile_offsets.append(len(buf))
            tile_bytecounts.append(len(compressed))
            buf.extend(compressed)

    # ── Page 1 strip data ───────────────────────────────────────────────────

    strip_offset = len(buf)
    strip_data = img1.tobytes()
    strip_bytecount = len(strip_data)
    buf.extend(strip_data)

    # ── External tag-value blocks for Page 0 ────────────────────────────────
    # TileOffsets: 4 × LONG8 = 32 bytes (> 8, cannot be inline)
    tile_offsets_pos = len(buf)
    for off in tile_offsets:
        buf.extend(struct.pack('<Q', off))

    # TileByteCounts: 4 × LONG8 = 32 bytes
    tile_bytecounts_pos = len(buf)
    for bc in tile_bytecounts:
        buf.extend(struct.pack('<Q', bc))

    # ── IFD 0 ───────────────────────────────────────────────────────────────

    ifd0_offset = len(buf)
    struct.pack_into('<Q', buf, first_ifd_pos, ifd0_offset)

    ifd0_tags = sorted(
        [
            (256, TIFF_SHORT, 1, encode_values(TIFF_SHORT, [W0])),
            (257, TIFF_SHORT, 1, encode_values(TIFF_SHORT, [H0])),
            (258, TIFF_SHORT, 1, encode_values(TIFF_SHORT, [16])),
            (259, TIFF_SHORT, 1, encode_values(TIFF_SHORT, [8])),       # DEFLATE
            (262, TIFF_SHORT, 1, encode_values(TIFF_SHORT, [1])),       # MinIsBlack
            (277, TIFF_SHORT, 1, encode_values(TIFF_SHORT, [1])),       # SamplesPerPixel
            (282, TIFF_RATIONAL, 1, encode_values(TIFF_RATIONAL, [(72, 1)])),
            (283, TIFF_RATIONAL, 1, encode_values(TIFF_RATIONAL, [(72, 1)])),
            (296, TIFF_SHORT, 1, encode_values(TIFF_SHORT, [2])),       # INCH
            (317, TIFF_SHORT, 1, encode_values(TIFF_SHORT, [2])),       # HORIZONTAL
            (322, TIFF_SHORT, 1, encode_values(TIFF_SHORT, [TILE_W])),
            (323, TIFF_SHORT, 1, encode_values(TIFF_SHORT, [TILE_H])),
            # External offsets for multi-value arrays:
            (324, TIFF_LONG8, n_tiles, struct.pack('<Q', tile_offsets_pos)),
            (325, TIFF_LONG8, n_tiles, struct.pack('<Q', tile_bytecounts_pos)),
        ],
        key=lambda t: t[0],
    )

    next_ifd_pos = write_ifd(buf, ifd0_tags)

    # ── IFD 1 ───────────────────────────────────────────────────────────────

    ifd1_offset = len(buf)
    struct.pack_into('<Q', buf, next_ifd_pos, ifd1_offset)

    ifd1_tags = sorted(
        [
            (256, TIFF_SHORT, 1, encode_values(TIFF_SHORT, [W1])),
            (257, TIFF_SHORT, 1, encode_values(TIFF_SHORT, [H1])),
            (258, TIFF_SHORT, 3, encode_values(TIFF_SHORT, [8, 8, 8])),  # 6 B inline
            (259, TIFF_SHORT, 1, encode_values(TIFF_SHORT, [1])),        # NONE
            (262, TIFF_SHORT, 1, encode_values(TIFF_SHORT, [2])),        # RGB
            (273, TIFF_LONG8, 1, encode_values(TIFF_LONG8, [strip_offset])),
            (277, TIFF_SHORT, 1, encode_values(TIFF_SHORT, [3])),
            (278, TIFF_SHORT, 1, encode_values(TIFF_SHORT, [H1])),      # RowsPerStrip
            (279, TIFF_LONG8, 1, encode_values(TIFF_LONG8, [strip_bytecount])),
            (282, TIFF_RATIONAL, 1, encode_values(TIFF_RATIONAL, [(72, 1)])),
            (283, TIFF_RATIONAL, 1, encode_values(TIFF_RATIONAL, [(72, 1)])),
            (284, TIFF_SHORT, 1, encode_values(TIFF_SHORT, [1])),        # CHUNKY
            (296, TIFF_SHORT, 1, encode_values(TIFF_SHORT, [2])),        # INCH
        ],
        key=lambda t: t[0],
    )

    write_ifd(buf, ifd1_tags)
    # next-IFD offset is already 0 from write_ifd → end of chain

    # ── Write output ────────────────────────────────────────────────────────

    with open(output_path, 'wb') as f:
        f.write(buf)

    print(f'BigTIFF written to {output_path}  ({len(buf)} bytes)')


if __name__ == '__main__':
    main()
