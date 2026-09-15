#!/usr/bin/env python3

"""
Pyramidal BigTIFF OME-TIFF writer — constructs valid TIFF binary using only
struct, zlib, and numpy.  No tifffile or other TIFF libraries.
"""

import struct
import sys
import zlib

import numpy as np

# ── TIFF constants ──────────────────────────────────────────────────────────

# Tag data types
ASCII = 2
SHORT = 3
LONG = 4
LONG8 = 16

# Tag codes
TAG_NEW_SUBFILE_TYPE = 254
TAG_IMAGE_WIDTH = 256
TAG_IMAGE_LENGTH = 257
TAG_BITS_PER_SAMPLE = 258
TAG_COMPRESSION = 259
TAG_PHOTOMETRIC = 262
TAG_IMAGE_DESCRIPTION = 270
TAG_SAMPLES_PER_PIXEL = 277
TAG_PLANAR_CONFIG = 284
TAG_PREDICTOR = 317
TAG_TILE_WIDTH = 322
TAG_TILE_LENGTH = 323
TAG_TILE_OFFSETS = 324
TAG_TILE_BYTE_COUNTS = 325
TAG_SUB_IFDS = 330

COMPRESSION_DEFLATE = 8
PHOTOMETRIC_RGB = 2
PLANAR_CHUNKY = 1
PREDICTOR_HORIZONTAL = 2


# ── Helpers ─────────────────────────────────────────────────────────────────

def ceil_div(a, b):
    return -(-a // b)


def inline_shorts(*vals):
    """Pack up to 4 uint16 values into a uint64 for BigTIFF inline storage."""
    raw = struct.pack('<' + 'H' * len(vals), *vals)
    raw = raw.ljust(8, b'\x00')
    return struct.unpack('<Q', raw)[0]


def apply_predictor(tile_3d, spp):
    """
    Horizontal differencing predictor for interleaved uint16 data.

    tile_3d: ndarray shape (rows, cols, samples), dtype uint16
    spp: samples per pixel (= samples)

    Returns flat predicted array shape (rows, cols*samples) dtype uint16.
    """
    rows, cols, samples = tile_3d.shape
    flat = tile_3d.reshape(rows, cols * samples).copy().astype(np.int32)
    if cols > 1:
        # Differencing with stride = spp, left to right, row-wise
        result = flat.copy()
        result[:, spp:] = (flat[:, spp:] - flat[:, :-spp]) & 0xFFFF
        return result.astype(np.uint16)
    return flat.astype(np.uint16)


def downsample_2x(page):
    """2×2 box-filter downsample; page shape (Y, X, S)."""
    h, w, s = page.shape
    h2, w2 = h // 2, w // 2
    return (
        page[: h2 * 2, : w2 * 2]
        .reshape(h2, 2, w2, 2, s)
        .mean(axis=(1, 3))
        .astype(page.dtype)
    )


def extract_tiles(page, tile_h, tile_w):
    """
    Extract tiles in row-major order, zero-padding edge tiles.
    Returns list of ndarray (tile_h, tile_w, S).
    """
    h, w, s = page.shape
    tiles = []
    for y in range(0, h, tile_h):
        for x in range(0, w, tile_w):
            tile = np.zeros((tile_h, tile_w, s), dtype=page.dtype)
            ah = min(tile_h, h - y)
            aw = min(tile_w, w - x)
            tile[:ah, :aw] = page[y : y + ah, x : x + aw]
            tiles.append(tile)
    return tiles


def compress_tiles(pages, tile_h, tile_w, spp):
    """Tile, predict, compress all pages; return list of bytes."""
    compressed = []
    for page in pages:
        for tile in extract_tiles(page, tile_h, tile_w):
            predicted = apply_predictor(tile, spp)
            compressed.append(zlib.compress(predicted.astype('<u2').tobytes()))
    return compressed


def build_ome_xml(T, Z, Y, X, S, num_pages):
    """Minimal valid OME-XML metadata string."""
    tiffdata = []
    ifd = 0
    for t in range(T):
        for z in range(Z):
            tiffdata.append(
                f'      <TiffData IFD="{ifd}" FirstT="{t}" FirstZ="{z}" '
                f'FirstC="0" PlaneCount="1"/>'
            )
            ifd += 1
    td = '\n'.join(tiffdata)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06"\n'
        '     xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n'
        '     xsi:schemaLocation="http://www.openmicroscopy.org/Schemas/OME/2016-06 '
        'http://www.openmicroscopy.org/Schemas/OME/2016-06/ome.xsd">\n'
        f'  <Image ID="Image:0" Name="output">\n'
        f'    <Pixels ID="Pixels:0" DimensionOrder="XYZCT" Type="uint16"\n'
        f'            SizeX="{X}" SizeY="{Y}" SizeZ="{Z}" SizeC="{S}" SizeT="{T}"\n'
        f'            Interleaved="true">\n'
        f'      <Channel ID="Channel:0:0" SamplesPerPixel="{S}"/>\n'
        f'{td}\n'
        f'    </Pixels>\n'
        f'  </Image>\n'
        f'</OME>'
    )


# ── IFD writing ─────────────────────────────────────────────────────────────

def ifd_byte_size(num_tags):
    """BigTIFF IFD size: 8 (count) + 20*tags + 8 (next offset)."""
    return 8 + 20 * num_tags + 8


def write_ifd(f, entries, next_ifd):
    """
    Write a BigTIFF IFD.  entries: sorted list of (tag, type, count, value_u64).
    """
    f.write(struct.pack('<Q', len(entries)))
    for tag, dtype, count, val in entries:
        f.write(struct.pack('<HHQQ', tag, dtype, count, val))
    f.write(struct.pack('<Q', next_ifd))


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    input_path = sys.argv[1]
    output_path = sys.argv[2]

    data = np.load(input_path)                   # (T, Z, Y, X, S) uint16
    T, Z, Y, X, S = data.shape
    num_pages = T * Z

    tile_w, tile_h = 64, 64
    tiles_x = ceil_div(X, tile_w)
    tiles_y = ceil_div(Y, tile_h)
    n_tiles = tiles_x * tiles_y                  # per page (full-res)

    sub_Y, sub_X = Y // 2, X // 2
    sub_tiles_x = ceil_div(sub_X, tile_w)
    sub_tiles_y = ceil_div(sub_Y, tile_h)
    sub_n_tiles = sub_tiles_x * sub_tiles_y      # per page (sub-res)

    # ── Flatten pages in T-major order ──────────────────────────────────────
    full_pages = [data[t, z] for t in range(T) for z in range(Z)]
    sub_pages = [downsample_2x(p) for p in full_pages]

    # ── Compress tiles ──────────────────────────────────────────────────────
    full_comp = compress_tiles(full_pages, tile_h, tile_w, S)
    sub_comp = compress_tiles(sub_pages, tile_h, tile_w, S)

    # ── OME-XML ─────────────────────────────────────────────────────────────
    ome_xml_bytes = build_ome_xml(T, Z, Y, X, S, num_pages).encode('utf-8') + b'\x00'

    # ── Write file ──────────────────────────────────────────────────────────
    with open(output_path, 'wb') as f:

        # 1. BigTIFF header (16 bytes)
        f.write(b'II')
        f.write(struct.pack('<H', 43))
        f.write(struct.pack('<H', 8))
        f.write(struct.pack('<H', 0))
        hdr_ifd_pos = f.tell()
        f.write(struct.pack('<Q', 0))            # placeholder first-IFD offset

        # 2. Write compressed tile data (full-res, then sub-res)
        full_offsets, full_sizes = [], []
        for blob in full_comp:
            full_offsets.append(f.tell())
            f.write(blob)
            full_sizes.append(len(blob))

        sub_offsets, sub_sizes = [], []
        for blob in sub_comp:
            sub_offsets.append(f.tell())
            f.write(blob)
            sub_sizes.append(len(blob))

        # 3. Write OME-XML
        ome_offset = f.tell()
        f.write(ome_xml_bytes)

        # 4. Write external tag-value arrays for main IFDs
        #    (TileOffsets and TileByteCounts arrays, each n_tiles LONG8s)
        ext_to_off = []   # file offset where each page's TileOffsets array starts
        ext_to_bc = []    # file offset where each page's TileByteCounts array starts
        for p in range(num_pages):
            base = p * n_tiles
            ext_to_off.append(f.tell())
            for i in range(n_tiles):
                f.write(struct.pack('<Q', full_offsets[base + i]))
            ext_to_bc.append(f.tell())
            for i in range(n_tiles):
                f.write(struct.pack('<Q', full_sizes[base + i]))

        # External arrays for sub-IFDs (only needed when sub_n_tiles > 1)
        sub_ext_to_off = []
        sub_ext_to_bc = []
        if sub_n_tiles > 1:
            for p in range(num_pages):
                base = p * sub_n_tiles
                sub_ext_to_off.append(f.tell())
                for i in range(sub_n_tiles):
                    f.write(struct.pack('<Q', sub_offsets[base + i]))
                sub_ext_to_bc.append(f.tell())
                for i in range(sub_n_tiles):
                    f.write(struct.pack('<Q', sub_sizes[base + i]))

        # 5. Pre-compute IFD file positions
        #    Main IFD 0 has ImageDescription (extra tag) → different tag count
        main_ntags = []
        for p in range(num_pages):
            # Tags: Width,Length,BPS,Compression,Photometric,SamplesPerPixel,
            #        PlanarConfig,Predictor,TileWidth,TileLength,
            #        TileOffsets,TileByteCounts,SubIFDs  = 13
            # + ImageDescription on page 0                  = +1
            main_ntags.append(14 if p == 0 else 13)
        sub_ntags = 13  # NewSubfileType instead of ImageDescription & SubIFDs

        cur = f.tell()
        main_ifd_pos = []
        for nt in main_ntags:
            main_ifd_pos.append(cur)
            cur += ifd_byte_size(nt)

        sub_ifd_pos = []
        for _ in range(num_pages):
            sub_ifd_pos.append(cur)
            cur += ifd_byte_size(sub_ntags)

        # Patch header with first IFD offset
        f.seek(hdr_ifd_pos)
        f.write(struct.pack('<Q', main_ifd_pos[0]))
        f.seek(0, 2)

        # 6. Write main IFDs
        for p in range(num_pages):
            assert f.tell() == main_ifd_pos[p]
            entries = [
                (TAG_IMAGE_WIDTH,       SHORT, 1, X),
                (TAG_IMAGE_LENGTH,      SHORT, 1, Y),
                (TAG_BITS_PER_SAMPLE,   SHORT, 3, inline_shorts(16, 16, 16)),
                (TAG_COMPRESSION,       SHORT, 1, COMPRESSION_DEFLATE),
                (TAG_PHOTOMETRIC,       SHORT, 1, PHOTOMETRIC_RGB),
                (TAG_SAMPLES_PER_PIXEL, SHORT, 1, S),
                (TAG_PLANAR_CONFIG,     SHORT, 1, PLANAR_CHUNKY),
                (TAG_PREDICTOR,         SHORT, 1, PREDICTOR_HORIZONTAL),
                (TAG_TILE_WIDTH,        SHORT, 1, tile_w),
                (TAG_TILE_LENGTH,       SHORT, 1, tile_h),
                (TAG_SUB_IFDS,          LONG8, 1, sub_ifd_pos[p]),
            ]
            if p == 0:
                entries.append(
                    (TAG_IMAGE_DESCRIPTION, ASCII, len(ome_xml_bytes), ome_offset)
                )
            # TileOffsets / TileByteCounts: inline if 1 tile, else external
            if n_tiles == 1:
                base = p * n_tiles
                entries.append((TAG_TILE_OFFSETS,     LONG8, 1, full_offsets[base]))
                entries.append((TAG_TILE_BYTE_COUNTS, LONG8, 1, full_sizes[base]))
            else:
                entries.append((TAG_TILE_OFFSETS,     LONG8, n_tiles, ext_to_off[p]))
                entries.append((TAG_TILE_BYTE_COUNTS, LONG8, n_tiles, ext_to_bc[p]))

            entries.sort()
            next_ifd = main_ifd_pos[p + 1] if p < num_pages - 1 else 0
            write_ifd(f, entries, next_ifd)

        # 7. Write sub-IFDs
        for p in range(num_pages):
            assert f.tell() == sub_ifd_pos[p]
            entries = [
                (TAG_NEW_SUBFILE_TYPE,  LONG,  1, 1),  # REDUCEDIMAGE
                (TAG_IMAGE_WIDTH,       SHORT, 1, sub_X),
                (TAG_IMAGE_LENGTH,      SHORT, 1, sub_Y),
                (TAG_BITS_PER_SAMPLE,   SHORT, 3, inline_shorts(16, 16, 16)),
                (TAG_COMPRESSION,       SHORT, 1, COMPRESSION_DEFLATE),
                (TAG_PHOTOMETRIC,       SHORT, 1, PHOTOMETRIC_RGB),
                (TAG_SAMPLES_PER_PIXEL, SHORT, 1, S),
                (TAG_PLANAR_CONFIG,     SHORT, 1, PLANAR_CHUNKY),
                (TAG_PREDICTOR,         SHORT, 1, PREDICTOR_HORIZONTAL),
                (TAG_TILE_WIDTH,        SHORT, 1, tile_w),
                (TAG_TILE_LENGTH,       SHORT, 1, tile_h),
            ]
            base = p * sub_n_tiles
            if sub_n_tiles == 1:
                entries.append((TAG_TILE_OFFSETS,     LONG8, 1, sub_offsets[base]))
                entries.append((TAG_TILE_BYTE_COUNTS, LONG8, 1, sub_sizes[base]))
            else:
                entries.append((TAG_TILE_OFFSETS,     LONG8, sub_n_tiles, sub_ext_to_off[p]))
                entries.append((TAG_TILE_BYTE_COUNTS, LONG8, sub_n_tiles, sub_ext_to_bc[p]))

            entries.sort()
            write_ifd(f, entries, 0)

    print(f'Wrote {output_path}')


if __name__ == '__main__':
    main()
