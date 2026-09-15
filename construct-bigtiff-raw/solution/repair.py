#!/usr/bin/env python3
"""
Repair a corrupted BigTIFF file by diagnosing and fixing structural issues.

Strategy:
  1. Parse the BigTIFF header and IFD chain
  2. Detect a broken IFD chain (missing page) and scan for the orphaned IFD
  3. Detect incorrect tag values by cross-checking metadata against data layout
  4. Detect tile offset ordering anomalies indicating swapped tiles
  5. Apply binary patches and write the repaired file
"""
import struct

# BigTIFF data type sizes
TYPE_SIZES = {
    1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1,
    8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 16: 8, 17: 8
}


def parse_ifd(data, offset):
    """Parse a BigTIFF IFD. Returns (entries, next_ifd, next_ptr_file_pos)."""
    count = struct.unpack_from('<Q', data, offset)[0]
    entries = {}
    pos = offset + 8
    for _ in range(count):
        tag = struct.unpack_from('<H', data, pos)[0]
        typ = struct.unpack_from('<H', data, pos + 2)[0]
        cnt = struct.unpack_from('<Q', data, pos + 4)[0]
        tsize = TYPE_SIZES.get(typ, 1)
        total = cnt * tsize
        if total <= 8:
            voff = pos + 12
        else:
            voff = struct.unpack_from('<Q', data, pos + 12)[0]
        entries[tag] = {
            'entry_offset': pos,
            'type': typ,
            'count': cnt,
            'value_offset': voff,
            'total_size': total,
        }
        pos += 20
    next_ptr_pos = pos
    next_ifd = struct.unpack_from('<Q', data, next_ptr_pos)[0]
    return entries, next_ifd, next_ptr_pos


def read_tag_uint(data, entry, index=0):
    """Read a single unsigned integer value from a tag entry."""
    typ = entry['type']
    voff = entry['value_offset']
    if typ == 3:  # SHORT
        return struct.unpack_from('<H', data, voff + index * 2)[0]
    elif typ == 4:  # LONG
        return struct.unpack_from('<I', data, voff + index * 4)[0]
    elif typ == 16:  # LONG8
        return struct.unpack_from('<Q', data, voff + index * 8)[0]
    elif typ == 1:  # BYTE
        return data[voff + index]
    else:
        raise ValueError(f"Unsupported uint type {typ}")


def scan_for_ifd(data, start, end):
    """Scan for a valid-looking BigTIFF IFD between start and end.

    Uses non-decreasing tag order check (allows duplicate tags, which
    some writers like tifffile produce for ImageDescription).
    """
    for pos in range(start, end - 28):
        count = struct.unpack_from('<Q', data, pos)[0]
        if not (5 <= count <= 30):
            continue
        ifd_end = pos + 8 + count * 20 + 8
        if ifd_end > len(data):
            continue
        # Verify tags are in non-decreasing order (TIFF spec: ascending;
        # tifffile may write duplicate tag 270 entries)
        tags = []
        valid = True
        for i in range(count):
            t = struct.unpack_from('<H', data, pos + 8 + i * 20)[0]
            if tags and t < tags[-1]:
                valid = False
                break
            tags.append(t)
        if not valid:
            continue
        # Require at least ImageWidth (256) and ImageLength (257)
        if 256 not in tags:
            continue
        if 257 not in tags:
            continue
        return pos
    return None


def fix_ifd_chain(data, ifd_offsets, next_ptr_positions):
    """If the IFD chain is truncated, scan for orphaned IFDs and restore links."""
    last_ifd_idx = len(ifd_offsets) - 1
    last_next_ptr = next_ptr_positions[last_ifd_idx]
    last_next_val = struct.unpack_from('<Q', data, last_next_ptr)[0]

    if last_next_val == 0:
        # Chain might be broken. Scan for orphaned IFD after last known IFD.
        search_start = last_next_ptr + 8
        found = scan_for_ifd(data, search_start, len(data))
        if found is not None:
            struct.pack_into('<Q', data, last_next_ptr, found)
            # Parse the found IFD and recurse
            entries, next_ifd, next_ptr = parse_ifd(data, found)
            ifd_offsets.append(found)
            next_ptr_positions.append(next_ptr)
            if next_ifd > 0:
                fix_ifd_chain(data, ifd_offsets, next_ptr_positions)


def fix_compression_tag(data, entries):
    """Detect and fix a mismatched Compression tag by checking strip sizes."""
    if 259 not in entries:
        return
    comp_val = read_tag_uint(data, entries[259])
    if comp_val == 1:
        return  # Already uncompressed, nothing to check

    # Get image dimensions
    width = read_tag_uint(data, entries[256])
    height = read_tag_uint(data, entries[257])
    bps = read_tag_uint(data, entries[258])
    spp = read_tag_uint(data, entries[277]) if 277 in entries else 1

    expected_raw_size = width * height * spp * (bps // 8)

    # Check strip byte count
    if 279 in entries:  # StripByteCounts
        bc = read_tag_uint(data, entries[279], 0)
        if bc == expected_raw_size:
            # Data is uncompressed but tag says otherwise; fix it
            comp_voff = entries[259]['value_offset']
            struct.pack_into('<H', data, comp_voff, 1)


def fix_tile_order(data, entries):
    """Detect and fix non-monotonic tile offsets (swapped tiles)."""
    if 324 not in entries or 325 not in entries:
        return

    n_tiles = entries[324]['count']
    to_voff = entries[324]['value_offset']
    tbc_voff = entries[325]['value_offset']

    # Read tile offsets
    offsets = []
    for i in range(n_tiles):
        offsets.append(read_tag_uint(data, entries[324], i))

    # Check monotonicity (tiles should be written sequentially)
    for i in range(len(offsets) - 1):
        if offsets[i] > offsets[i + 1]:
            # Swap entries i and i+1 in both TileOffsets and TileByteCounts
            tsize = TYPE_SIZES[entries[324]['type']]
            for base in [to_voff, tbc_voff]:
                a = base + i * tsize
                b = base + (i + 1) * tsize
                tmp_a = bytes(data[a:a + tsize])
                tmp_b = bytes(data[b:b + tsize])
                data[a:a + tsize] = tmp_b
                data[b:b + tsize] = tmp_a
            # Re-read and check again
            offsets[i], offsets[i + 1] = offsets[i + 1], offsets[i]


def main():
    # Read corrupted file
    with open('/app/corrupted.tif', 'rb') as f:
        data = bytearray(f.read())

    # Verify BigTIFF header
    assert data[0:2] == b'II', "Not little-endian TIFF"
    assert struct.unpack_from('<H', data, 2)[0] == 43, "Not BigTIFF"

    first_ifd = struct.unpack_from('<Q', data, 8)[0]

    # Walk the IFD chain
    ifd_offsets = []
    next_ptr_positions = []
    offset = first_ifd
    while offset > 0:
        entries, next_ifd, next_ptr = parse_ifd(data, offset)
        ifd_offsets.append(offset)
        next_ptr_positions.append(next_ptr)
        offset = next_ifd

    # --- Fix 1: Restore broken IFD chain ---
    fix_ifd_chain(data, ifd_offsets, next_ptr_positions)

    # Now re-parse all IFDs with the fixed chain
    all_entries = []
    for ifd_off in ifd_offsets:
        entries, _, _ = parse_ifd(data, ifd_off)
        all_entries.append(entries)

    # --- Fix 2: Fix compression tags ---
    for entries in all_entries:
        fix_compression_tag(data, entries)

    # --- Fix 3: Fix tile offset ordering ---
    for entries in all_entries:
        fix_tile_order(data, entries)

    # Write repaired file
    with open('/app/repaired.tif', 'wb') as f:
        f.write(data)


if __name__ == '__main__':
    main()
