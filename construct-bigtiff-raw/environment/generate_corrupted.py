#!/usr/bin/env python3
"""Generate a corrupted BigTIFF file with three distinct structural corruptions."""
import numpy as np
import tifffile
import struct
import os

os.makedirs('/app', exist_ok=True)

# ---- Generate deterministic calibration data ----
# Page 0: 512x512 uint16 grayscale
y0, x0 = np.mgrid[0:512, 0:512]
p0_data = ((y0.astype(np.int64) * 512 + x0.astype(np.int64)) % 65536).astype(np.uint16)

# Page 1: 256x256 uint8 RGB
y1, x1 = np.mgrid[0:256, 0:256]
p1_data = np.stack([
    (y1 % 256).astype(np.uint8),
    (x1 % 256).astype(np.uint8),
    ((y1 + x1) % 256).astype(np.uint8),
], axis=-1)

# Page 2: 384x384 uint16 grayscale
y2, x2 = np.mgrid[0:384, 0:384]
p2_data = ((y2.astype(np.int64) * 3 + x2.astype(np.int64) * 7 + 42) % 65536).astype(np.uint16)

# ---- Write valid BigTIFF with per-page descriptions ----
with tifffile.TiffWriter('/app/corrupted.tif', bigtiff=True) as tif:
    tif.write(p0_data, photometric='minisblack', tile=(256, 256),
              compression='zlib', predictor=True,
              description='CAL:7A3F-512G:T=2024-03-15T08:42:11Z')
    tif.write(p1_data, photometric='rgb', rowsperstrip=256,
              description='REF:B92C-256RGB:T=2024-03-15T09:15:33Z')
    tif.write(p2_data, photometric='minisblack', rowsperstrip=384,
              compression='zlib',
              description='BKG:E51D-384G:T=2024-03-15T10:03:47Z')

# ---- Read file as raw bytes for corruption ----
with open('/app/corrupted.tif', 'rb') as f:
    raw = bytearray(f.read())

TYPE_SIZES = {1:1, 2:1, 3:2, 4:4, 5:8, 6:1, 7:1, 8:2, 9:4, 10:8, 11:4, 12:8, 16:8, 17:8}

def get_ifd_offsets(data):
    offsets = []
    o = struct.unpack_from('<Q', data, 8)[0]
    while o > 0:
        offsets.append(o)
        count = struct.unpack_from('<Q', data, o)[0]
        next_pos = o + 8 + count * 20
        o = struct.unpack_from('<Q', data, next_pos)[0]
    return offsets

def find_tag(data, ifd_offset, tag_code):
    count = struct.unpack_from('<Q', data, ifd_offset)[0]
    pos = ifd_offset + 8
    for _ in range(count):
        code = struct.unpack_from('<H', data, pos)[0]
        if code == tag_code:
            return pos
        pos += 20
    return None

def get_value_offset(data, entry_offset):
    typ = struct.unpack_from('<H', data, entry_offset + 2)[0]
    cnt = struct.unpack_from('<Q', data, entry_offset + 4)[0]
    tsize = TYPE_SIZES.get(typ, 1)
    if cnt * tsize <= 8:
        return entry_offset + 12
    else:
        return struct.unpack_from('<Q', data, entry_offset + 12)[0]

ifd_offsets = get_ifd_offsets(raw)
assert len(ifd_offsets) == 3, f"Expected 3 IFDs, got {len(ifd_offsets)}"

# ---- Corruption 1: Swap TileOffsets[1] <-> [2] and TileByteCounts[1] <-> [2] ----
# This transposes top-right and bottom-left image quadrants in page 0
to_entry = find_tag(raw, ifd_offsets[0], 324)   # TileOffsets
tbc_entry = find_tag(raw, ifd_offsets[0], 325)   # TileByteCounts
to_voff = get_value_offset(raw, to_entry)
tbc_voff = get_value_offset(raw, tbc_entry)

for base in [to_voff, tbc_voff]:
    a = base + 1 * 8
    b = base + 2 * 8
    tmp_a = bytes(raw[a:a+8])
    tmp_b = bytes(raw[b:b+8])
    raw[a:a+8] = tmp_b
    raw[b:b+8] = tmp_a

# ---- Corruption 2: Change Compression from 1 (None) to 5 (LZW) in page 1 ----
# tifffile will fail trying to LZW-decode raw uncompressed RGB data
comp_entry = find_tag(raw, ifd_offsets[1], 259)  # Compression
comp_voff = get_value_offset(raw, comp_entry)
struct.pack_into('<H', raw, comp_voff, 5)

# ---- Corruption 3: Zero next-IFD pointer after page 1 ----
# This hides page 2 entirely from normal IFD chain traversal
count1 = struct.unpack_from('<Q', raw, ifd_offsets[1])[0]
next_ptr_pos = ifd_offsets[1] + 8 + count1 * 20
struct.pack_into('<Q', raw, next_ptr_pos, 0)

# ---- Write corrupted file ----
with open('/app/corrupted.tif', 'wb') as f:
    f.write(raw)

print(f"Generated corrupted BigTIFF: {len(raw)} bytes")
