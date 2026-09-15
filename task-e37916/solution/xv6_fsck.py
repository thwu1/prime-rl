#!/usr/bin/env python3

"""
xv6 Filesystem Consistency Checker (fsck)

Parses a raw xv6 filesystem image and detects inconsistencies in the
superblock, block bitmap, inode block references, directory entries,
and nlink counts.

Usage: xv6-fsck <image_path>
Output: JSON report to stdout
"""

import struct
import sys
import json

# ── xv6 filesystem constants ──
BSIZE = 1024
NDIRECT = 12
NINDIRECT = BSIZE // 4   # 256
IPB = BSIZE // 64        # 16  (inodes per block)
BPB = BSIZE * 8          # 8192 (bitmap bits per block)
T_DIR = 1
T_FILE = 2
T_DEVICE = 3
FSMAGIC = 0x10203040
DIRSIZ = 14
ROOTINO = 1


def read_superblock(data):
    """Parse the superblock from block 1."""
    fields = struct.unpack_from('<IIIIIIII', data, BSIZE)
    return {
        'magic': fields[0],
        'size': fields[1],
        'nblocks': fields[2],
        'ninodes': fields[3],
        'nlog': fields[4],
        'logstart': fields[5],
        'inodestart': fields[6],
        'bmapstart': fields[7],
    }


def compute_datastart(sb):
    """Compute the first data block number from superblock fields."""
    niblocks = (sb['ninodes'] + IPB - 1) // IPB
    nbmapblocks = (sb['size'] + BPB - 1) // BPB
    return sb['bmapstart'] + nbmapblocks


def read_inode(data, inum, sb):
    """Read an on-disk inode (dinode) by inode number."""
    block = inum // IPB + sb['inodestart']
    off = (inum % IPB) * 64
    pos = block * BSIZE + off
    typ, major, minor, nlink, size = struct.unpack_from('<hhhhI', data, pos)
    addrs = list(struct.unpack_from('<13I', data, pos + 12))
    return {
        'type': typ,
        'major': major,
        'minor': minor,
        'nlink': nlink,
        'size': size,
        'addrs': addrs,
    }


def get_bitmap_bit(data, block, sb):
    """Return 1 if bitmap says block is allocated, 0 otherwise."""
    bmap_block_idx = block // BPB
    bit = block % BPB
    byte_offset = (sb['bmapstart'] + bmap_block_idx) * BSIZE + bit // 8
    if byte_offset >= len(data):
        return 0
    return (data[byte_offset] >> (bit % 8)) & 1


def collect_inode_blocks(data, inode, sb, datastart):
    """
    Collect all block numbers referenced by an inode.
    Returns list of (block_number, is_valid) tuples.
    A block is valid if it's in range [datastart, sb['size']).
    Block number 0 means "not allocated" and is skipped.
    """
    blocks = []

    # Direct blocks
    for i in range(NDIRECT):
        b = inode['addrs'][i]
        if b != 0:
            blocks.append(b)

    # Indirect block
    indirect_ptr = inode['addrs'][NDIRECT]
    if indirect_ptr != 0:
        blocks.append(indirect_ptr)  # The indirect block itself is referenced

        # Read entries from the indirect block if it's accessible
        if indirect_ptr < sb['size']:
            indirect_pos = indirect_ptr * BSIZE
            if indirect_pos + BSIZE <= len(data):
                for j in range(NINDIRECT):
                    entry = struct.unpack_from('<I', data, indirect_pos + j * 4)[0]
                    if entry != 0:
                        blocks.append(entry)

    return blocks


def read_directory_entries(data, inode, sb):
    """
    Read all directory entries from a directory inode.
    Returns list of {'inum': int, 'name': str} for non-free entries.
    """
    entries = []
    if inode['type'] != T_DIR:
        return entries

    size = inode['size']
    offset = 0

    while offset < size:
        # Determine which block this offset falls in
        block_idx = offset // BSIZE
        offset_in_block = offset % BSIZE

        if block_idx < NDIRECT:
            block_addr = inode['addrs'][block_idx]
        elif inode['addrs'][NDIRECT] != 0:
            indirect_ptr = inode['addrs'][NDIRECT]
            if indirect_ptr >= sb['size'] or indirect_ptr * BSIZE + BSIZE > len(data):
                offset += 16
                continue
            indirect_pos = indirect_ptr * BSIZE
            inner_idx = block_idx - NDIRECT
            if inner_idx >= NINDIRECT:
                break
            block_addr = struct.unpack_from('<I', data, indirect_pos + inner_idx * 4)[0]
        else:
            offset += 16
            continue

        if block_addr == 0 or block_addr >= sb['size'] or block_addr * BSIZE + BSIZE > len(data):
            offset += 16
            continue

        pos = block_addr * BSIZE + offset_in_block
        if pos + 16 > len(data):
            break

        inum = struct.unpack_from('<H', data, pos)[0]
        name_raw = data[pos + 2:pos + 16]

        if inum != 0:
            # Decode name: find NUL or take all DIRSIZ bytes
            null_pos = name_raw.find(0)
            if null_pos >= 0:
                name = name_raw[:null_pos].decode('ascii', errors='replace')
            else:
                name = name_raw.decode('ascii', errors='replace')
            entries.append({'inum': inum, 'name': name})

        offset += 16

    return entries


def fsck(image_path):
    """Run all consistency checks on the given xv6 filesystem image."""
    with open(image_path, 'rb') as f:
        data = bytearray(f.read())

    sb = read_superblock(data)
    errors = []

    # Validate magic number
    if sb['magic'] != FSMAGIC:
        return {'errors': [{'type': 'BAD_MAGIC'}]}

    datastart = compute_datastart(sb)

    # ── Pass 1: Read all inodes and collect block references ──
    all_inodes = {}
    block_refs = {}  # block -> list of inodes referencing it

    for inum in range(sb['ninodes']):
        inode = read_inode(data, inum, sb)
        all_inodes[inum] = inode

        if inode['type'] == 0:
            continue

        blocks = collect_inode_blocks(data, inode, sb, datastart)
        for b in blocks:
            if b not in block_refs:
                block_refs[b] = []
            block_refs[b].append(inum)

    # ── Check 1: Invalid block references ──
    for block, inodes in block_refs.items():
        if block >= sb['size'] or block < datastart:
            for inum in inodes:
                errors.append({
                    'type': 'INVALID_BLOCK_REF',
                    'inode': inum,
                    'block': block,
                })

    # ── Check 2: Duplicate block references ──
    for block, inodes in block_refs.items():
        if len(inodes) > 1 and datastart <= block < sb['size']:
            errors.append({
                'type': 'DUPLICATE_BLOCK_REF',
                'block': block,
                'inodes': sorted(inodes),
            })

    # ── Check 3: Bitmap consistency (data blocks only) ──
    for b in range(datastart, sb['size']):
        bitmap_set = get_bitmap_bit(data, b, sb)
        referenced = b in block_refs

        if referenced and not bitmap_set:
            # Only report if the block is in valid data range
            # (invalid refs are already caught above)
            ref_inodes = block_refs[b]
            # Only include inodes whose reference to this block is valid (data range)
            if datastart <= b < sb['size']:
                errors.append({
                    'type': 'BITMAP_MARKED_FREE',
                    'block': b,
                    'inodes': sorted(ref_inodes),
                })
        elif bitmap_set and not referenced:
            errors.append({
                'type': 'BITMAP_MARKED_USED',
                'block': b,
            })

    # ── Pass 2: Walk directories to count nlink references ──
    dir_refs = {}  # inum -> count of directory entries pointing to it (excl ".")

    for inum in range(sb['ninodes']):
        inode = all_inodes[inum]
        if inode['type'] != T_DIR:
            continue

        entries = read_directory_entries(data, inode, sb)
        for entry in entries:
            if entry['name'] == '.':
                continue  # "." does not contribute to nlink
            target = entry['inum']
            if target not in dir_refs:
                dir_refs[target] = 0
            dir_refs[target] += 1

    # ── Check 4: Orphan inodes ──
    for inum in range(1, sb['ninodes']):  # Skip inode 0 (always unused)
        inode = all_inodes[inum]
        if inode['type'] == 0:
            continue

        ref_count = dir_refs.get(inum, 0)
        if ref_count == 0:
            errors.append({
                'type': 'ORPHAN_INODE',
                'inode': inum,
            })

    # ── Check 5: nlink mismatches ──
    for inum in range(1, sb['ninodes']):
        inode = all_inodes[inum]
        if inode['type'] == 0:
            continue

        expected = dir_refs.get(inum, 0)
        actual = inode['nlink']

        if expected != actual:
            errors.append({
                'type': 'INODE_NLINK_MISMATCH',
                'inode': inum,
                'expected': expected,
                'actual': actual,
            })

    return {'errors': errors}


def main():
    if len(sys.argv) < 2:
        print("Usage: xv6-fsck <image_path>", file=sys.stderr)
        sys.exit(1)

    image_path = sys.argv[1]
    report = fsck(image_path)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
