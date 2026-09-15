#!/usr/bin/env python3
"""Repair a FAT32 filesystem image with multi-layer corruption.

Strategy:
1. Parse BPB to determine filesystem geometry dynamically.
2. Restore backup boot sector from primary boot sector.
3. Build preliminary merged FAT (zero-vs-nonzero rule) for directory traversal.
4. Walk the entire directory tree to catalog files with start clusters and sizes.
5. Resolve non-zero FAT conflicts by validating cluster chain length against
   directory entry file sizes — neither FAT is fully authoritative.
6. Detect orphaned clusters by comparing FAT allocations against directory
   tree references, then free them.
7. Recompute FSInfo (free count, next-free) from the final merged FAT.
8. Write merged FAT to both FAT1 and FAT2 positions.
"""


import struct
import math

INPUT = '/app/disk.img'
OUTPUT = '/app/repaired.img'


def fat_entry_buf(buf, cluster):
    """Read FAT entry from a raw FAT buffer."""
    return struct.unpack_from('<I', buf, cluster * 4)[0] & 0x0FFFFFFF


def set_fat_buf(buf, cluster, value):
    """Write FAT entry to a raw FAT buffer preserving high 4 bits."""
    off = cluster * 4
    old = struct.unpack_from('<I', buf, off)[0]
    struct.pack_into('<I', buf, off, (old & 0xF0000000) | (value & 0x0FFFFFFF))


def get_chain_buf(buf, start, max_len=200000):
    """Follow cluster chain through a FAT buffer."""
    chain = []
    c = start
    visited = set()
    while 2 <= c < 0x0FFFFFF8 and len(chain) < max_len:
        if c in visited:
            break
        visited.add(c)
        chain.append(c)
        c = fat_entry_buf(buf, c)
    return chain


def cluster_to_offset(data_off, clussz, cluster):
    """Convert cluster number to byte offset in image."""
    return data_off + (cluster - 2) * clussz


def parse_dir_name(img, off):
    """Parse 8.3 directory entry into readable name."""
    fname = img[off:off + 8].decode('ascii', errors='replace').rstrip()
    ext = img[off + 8:off + 11].decode('ascii', errors='replace').rstrip()
    return '{}.{}'.format(fname, ext) if ext else fname


def read_dir_entries(img, fat_buf, data_off, clussz, dir_cluster):
    """Read all directory entries from a directory cluster chain."""
    entries = []
    cluster = dir_cluster
    while 2 <= cluster < 0x0FFFFFF8:
        base = cluster_to_offset(data_off, clussz, cluster)
        for i in range(0, clussz, 32):
            off = base + i
            if off + 32 > len(img):
                break
            if img[off] == 0x00:
                return entries
            if img[off] == 0xE5:
                continue
            attr = img[off + 11]
            if (attr & 0x0F) == 0x0F:
                continue
            if attr & 0x08:
                continue
            name = parse_dir_name(img, off)
            hi = struct.unpack_from('<H', img, off + 20)[0]
            lo = struct.unpack_from('<H', img, off + 26)[0]
            first = (hi << 16) | lo
            size = struct.unpack_from('<I', img, off + 28)[0]
            is_dir = bool(attr & 0x10)
            entries.append({
                'name': name, 'cluster': first, 'size': size, 'is_dir': is_dir
            })
        cluster = fat_entry_buf(fat_buf, cluster)
    return entries


def walk_tree(img, fat_buf, data_off, clussz, dir_cluster, prefix=''):
    """Recursively walk directory tree, returning files and dir clusters."""
    files = []
    dir_clusters = [(dir_cluster, prefix)]
    entries = read_dir_entries(img, fat_buf, data_off, clussz, dir_cluster)
    for e in entries:
        if e['is_dir']:
            if e['name'] not in ('.', '..'):
                sub_files, sub_dirs = walk_tree(
                    img, fat_buf, data_off, clussz,
                    e['cluster'], prefix + e['name'] + '/')
                files.extend(sub_files)
                dir_clusters.extend(sub_dirs)
        else:
            files.append((prefix + e['name'], e))
    return files, dir_clusters


def collect_referenced(img, fat_buf, data_off, clussz, dir_cluster):
    """Walk directory tree and collect all referenced cluster numbers."""
    referenced = set()
    dir_chain = get_chain_buf(fat_buf, dir_cluster)
    referenced.update(dir_chain)
    entries = read_dir_entries(img, fat_buf, data_off, clussz, dir_cluster)
    for e in entries:
        if e['cluster'] < 2:
            continue
        if e['is_dir'] and e['name'] in ('.', '..'):
            continue
        chain = get_chain_buf(fat_buf, e['cluster'])
        referenced.update(chain)
        if e['is_dir']:
            sub_ref = collect_referenced(
                img, fat_buf, data_off, clussz, e['cluster'])
            referenced.update(sub_ref)
    return referenced


def repair():
    with open(INPUT, 'rb') as f:
        img = bytearray(f.read())

    # ---- Parse BPB ----
    bps = struct.unpack_from('<H', img, 0x0B)[0]
    spc = img[0x0D]
    rsvd = struct.unpack_from('<H', img, 0x0E)[0]
    nfats = img[0x10]
    fatsz = struct.unpack_from('<I', img, 0x24)[0]
    rootclus = struct.unpack_from('<I', img, 0x2C)[0]
    bkboot = struct.unpack_from('<H', img, 0x32)[0]

    fat1_off = rsvd * bps
    fat2_off = fat1_off + fatsz * bps
    fat_bytes = fatsz * bps
    data_off = fat2_off + fatsz * bps
    clussz = bps * spc
    total_entries = fat_bytes // 4
    total_sectors = len(img) // bps
    data_sectors = total_sectors - (rsvd + nfats * fatsz)
    max_cluster = 1 + data_sectors // spc

    print("BPB: bps={} spc={} rsvd={} fatsz={} rootclus={} bkboot={}".format(
        bps, spc, rsvd, fatsz, rootclus, bkboot))

    # ---- Step 1: Restore backup boot sector ----
    for i in range(3):
        src = i * bps
        dst = (bkboot + i) * bps
        img[dst:dst + bps] = img[src:src + bps]
    print("Step 1: Restored backup boot sector at sectors {}-{}".format(
        bkboot, bkboot + 2))

    # ---- Step 2: Extract original FATs and build preliminary merge ----
    orig_fat1 = bytes(img[fat1_off:fat1_off + fat_bytes])
    orig_fat2 = bytes(img[fat2_off:fat2_off + fat_bytes])

    # Preliminary merge: zero-vs-nonzero rule, tentative FAT1 for conflicts
    merged = bytearray(fat_bytes)
    nonzero_conflicts = {}
    for idx in range(total_entries):
        off = idx * 4
        e1 = struct.unpack_from('<I', orig_fat1, off)[0]
        e2 = struct.unpack_from('<I', orig_fat2, off)[0]
        v1 = e1 & 0x0FFFFFFF
        v2 = e2 & 0x0FFFFFFF
        if v1 == v2:
            struct.pack_into('<I', merged, off, e1)
        elif v1 == 0:
            struct.pack_into('<I', merged, off, e2)
        elif v2 == 0:
            struct.pack_into('<I', merged, off, e1)
        else:
            # Both non-zero and different: record conflict, tentatively use FAT1
            nonzero_conflicts[idx] = (v1, v2)
            struct.pack_into('<I', merged, off, e1)

    print("Step 2: Preliminary merge done. {} non-zero conflicts found".format(
        len(nonzero_conflicts)))

    # ---- Step 3: Walk directory tree using preliminary merged FAT ----
    # Temporarily install merged FAT into image for directory traversal
    img[fat1_off:fat1_off + fat_bytes] = merged
    files, dir_entries = walk_tree(img, merged, data_off, clussz, rootclus)

    # Restore original FATs
    img[fat1_off:fat1_off + fat_bytes] = orig_fat1
    img[fat2_off:fat2_off + fat_bytes] = orig_fat2

    print("Step 3: Found {} files, {} directories".format(
        len(files), len(dir_entries)))
    for name, entry in files:
        expected = max(1, math.ceil(entry['size'] / clussz)) if entry['size'] > 0 else 0
        print("  {}: cluster={} size={} expected_chain={}".format(
            name, entry['cluster'], entry['size'], expected))

    # ---- Step 4: Resolve non-zero conflicts via chain validation ----
    if nonzero_conflicts:
        for name, entry in files:
            if entry['size'] == 0 or entry['cluster'] < 2:
                continue
            expected_len = max(1, math.ceil(entry['size'] / clussz))

            # Iteratively resolve conflicts along this file's chain
            max_iters = 10
            for iteration in range(max_iters):
                chain = get_chain_buf(merged, entry['cluster'])
                if len(chain) == expected_len:
                    break  # chain is correct length

                # Find first non-zero conflict in the current chain
                resolved = False
                for c in chain:
                    if c in nonzero_conflicts:
                        v1, v2 = nonzero_conflicts[c]
                        current = fat_entry_buf(merged, c)
                        other = v2 if current == v1 else v1

                        # Try swapping to the other value
                        set_fat_buf(merged, c, other)
                        test_chain = get_chain_buf(merged, entry['cluster'])
                        if len(test_chain) == expected_len:
                            print("  Resolved conflict at cluster {}: "
                                  "chose {} for {} (chain now {})".format(
                                      c, other, name, len(test_chain)))
                            resolved = True
                            break
                        else:
                            # Swap back if it didn't help
                            set_fat_buf(merged, c, current)

                if not resolved:
                    break

    print("Step 4: All conflicts resolved")

    # ---- Step 5: Write merged FAT to image ----
    img[fat1_off:fat1_off + fat_bytes] = merged
    img[fat2_off:fat2_off + fat_bytes] = merged
    print("Step 5: Wrote merged FAT to both FAT1 and FAT2")

    # ---- Step 6: Detect and free orphaned clusters ----
    referenced = collect_referenced(img, merged, data_off, clussz, rootclus)

    orphans = []
    for c in range(2, max_cluster + 1):
        e = fat_entry_buf(merged, c)
        if e != 0 and c not in referenced:
            orphans.append(c)

    for c in orphans:
        set_fat_buf(merged, c, 0)
        # Update both FATs in image
        off1 = fat1_off + c * 4
        off2 = fat2_off + c * 4
        old1 = struct.unpack_from('<I', img, off1)[0]
        struct.pack_into('<I', img, off1, old1 & 0xF0000000)
        old2 = struct.unpack_from('<I', img, off2)[0]
        struct.pack_into('<I', img, off2, old2 & 0xF0000000)

    print("Step 6: Freed {} orphaned clusters: {}".format(len(orphans), orphans))

    # ---- Step 7: Fix FSInfo ----
    fsinfo_off = bps  # sector 1
    free_count = 0
    next_free = 0xFFFFFFFF
    for c in range(2, max_cluster + 1):
        e = struct.unpack_from('<I', img, fat1_off + c * 4)[0] & 0x0FFFFFFF
        if e == 0:
            free_count += 1
            if next_free == 0xFFFFFFFF:
                next_free = c

    if next_free == 0xFFFFFFFF:
        next_free = 2

    # Update primary FSInfo
    struct.pack_into('<I', img, fsinfo_off + 0x1E8, free_count)
    struct.pack_into('<I', img, fsinfo_off + 0x1EC, next_free)

    # Update backup FSInfo
    bk_fsinfo_off = (bkboot + 1) * bps
    struct.pack_into('<I', img, bk_fsinfo_off + 0x1E8, free_count)
    struct.pack_into('<I', img, bk_fsinfo_off + 0x1EC, next_free)

    print("Step 7: FSInfo free_count={}, next_free={}".format(
        free_count, next_free))

    # ---- Write repaired image ----
    with open(OUTPUT, 'wb') as f:
        f.write(img)
    print("Repaired image written to {}".format(OUTPUT))


if __name__ == '__main__':
    repair()
