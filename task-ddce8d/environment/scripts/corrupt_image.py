#!/usr/bin/env python3
"""Apply multi-layer corruption to a FAT32 filesystem image.

Corruptions applied:
1. Backup boot sector (3 sectors at BPB_BkBootSec) zeroed
2. FSInfo sector: free_count and next_free set to 0
3. FAT1 entries zeroed for specific files (FAT2 intact for those)
4. FAT2 entries zeroed for different files (FAT1 intact for those)
5. Conflicting non-zero entries: both FATs have different non-zero values
   for specific cluster entries, requiring chain validation to resolve
6. Orphaned cluster chain: clusters allocated in both FATs but unreferenced
   by any directory entry
"""
import struct
import sys


def read_img(path):
    with open(path, 'rb') as f:
        return bytearray(f.read())


def write_img(data, path):
    with open(path, 'wb') as f:
        f.write(data)


def parse_bpb(img):
    bps = struct.unpack_from('<H', img, 0x0B)[0]
    spc = img[0x0D]
    rsvd = struct.unpack_from('<H', img, 0x0E)[0]
    nfats = img[0x10]
    fatsz = struct.unpack_from('<I', img, 0x24)[0]
    rootclus = struct.unpack_from('<I', img, 0x2C)[0]
    bkboot = struct.unpack_from('<H', img, 0x32)[0]
    fat1 = rsvd * bps
    fat2 = fat1 + fatsz * bps
    fatbytes = fatsz * bps
    data = fat2 + fatsz * bps
    clussz = bps * spc
    total_sectors = len(img) // bps
    data_sectors = total_sectors - (rsvd + nfats * fatsz)
    max_cluster = 1 + data_sectors // spc
    return {
        'bps': bps, 'spc': spc, 'rsvd': rsvd, 'nfats': nfats,
        'fatsz': fatsz, 'rootclus': rootclus, 'bkboot': bkboot,
        'fat1': fat1, 'fat2': fat2, 'fatbytes': fatbytes,
        'data': data, 'clussz': clussz, 'max_cluster': max_cluster
    }


def fat_entry(img, p, cluster, fat_num=1):
    base = p['fat1'] if fat_num == 1 else p['fat2']
    return struct.unpack_from('<I', img, base + cluster * 4)[0] & 0x0FFFFFFF


def set_fat(img, p, cluster, value, fat_num=1):
    base = p['fat1'] if fat_num == 1 else p['fat2']
    off = base + cluster * 4
    old = struct.unpack_from('<I', img, off)[0]
    struct.pack_into('<I', img, off, (old & 0xF0000000) | (value & 0x0FFFFFFF))


def set_fat_both(img, p, cluster, value):
    set_fat(img, p, cluster, value, 1)
    set_fat(img, p, cluster, value, 2)


def cluster_offset(p, cluster):
    return p['data'] + (cluster - 2) * p['clussz']


def get_chain(img, p, start_cluster):
    chain = []
    c = start_cluster
    visited = set()
    while 2 <= c < 0x0FFFFFF8:
        if c in visited:
            break
        visited.add(c)
        chain.append(c)
        c = fat_entry(img, p, c)
    return chain


def parse_dir_name(img, off):
    """Parse 8.3 directory entry name into readable form."""
    fname = img[off:off + 8].decode('ascii', errors='replace').rstrip()
    ext = img[off + 8:off + 11].decode('ascii', errors='replace').rstrip()
    return '{}.{}'.format(fname, ext) if ext else fname


def find_dir_entries(img, p, dir_cluster):
    """Find all entries in a directory."""
    entries = []
    cluster = dir_cluster
    while 2 <= cluster < 0x0FFFFFF8:
        base = cluster_offset(p, cluster)
        for i in range(0, p['clussz'], 32):
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
        cluster = fat_entry(img, p, cluster)
    return entries


def find_all_files(img, p, dir_cluster, prefix=''):
    """Recursively find all files in the directory tree."""
    files = {}
    entries = find_dir_entries(img, p, dir_cluster)
    for e in entries:
        if e['is_dir']:
            if e['name'] not in ('.', '..'):
                sub = find_all_files(img, p, e['cluster'],
                                     prefix + e['name'] + '/')
                files.update(sub)
        else:
            files[prefix + e['name']] = {
                'cluster': e['cluster'],
                'size': e['size'],
                'chain': get_chain(img, p, e['cluster'])
            }
    return files


def find_free_clusters(img, p, count, exclude=None, start_from=500):
    """Find free clusters starting from a given cluster number."""
    if exclude is None:
        exclude = set()
    free = []
    for c in range(start_from, p['max_cluster'] + 1):
        if c in exclude:
            continue
        if fat_entry(img, p, c) == 0:
            free.append(c)
            if len(free) == count:
                return free
    raise RuntimeError("Not enough free clusters")


def corrupt(in_path, out_path):
    img = read_img(in_path)
    p = parse_bpb(img)
    print("BPB: bps={} spc={} rsvd={} fatsz={} rootclus={} bkboot={}".format(
        p['bps'], p['spc'], p['rsvd'], p['fatsz'], p['rootclus'], p['bkboot']))

    # Find all files recursively
    files = find_all_files(img, p, p['rootclus'])
    print("Found {} files:".format(len(files)))

    # Collect all used clusters (files + directories)
    used = set()
    for info in files.values():
        used.update(info['chain'])
    root_chain = get_chain(img, p, p['rootclus'])
    used.update(root_chain)
    root_entries = find_dir_entries(img, p, p['rootclus'])
    for e in root_entries:
        if e['is_dir'] and e['name'] not in ('.', '..'):
            used.update(get_chain(img, p, e['cluster']))

    for name, info in sorted(files.items()):
        print("  {}: cluster={} size={} chain_len={}".format(
            name, info['cluster'], info['size'], len(info['chain'])))

    # Build file lookup by uppercase basename
    file_map = {}
    for name, info in files.items():
        base = name.split('/')[-1].upper()
        file_map[base] = (name, info)

    # --- C1: Zero backup boot sector ---
    bps = p['bps']
    bkboot = p['bkboot']
    for i in range(3):
        start = (bkboot + i) * bps
        img[start:start + bps] = b'\x00' * bps
    print("C1: Zeroed backup boot sector at sectors {}-{}".format(
        bkboot, bkboot + 2))

    # --- C2: Corrupt FSInfo ---
    struct.pack_into('<I', img, bps + 0x1E8, 0)
    struct.pack_into('<I', img, bps + 0x1EC, 0)
    print("C2: FSInfo free_count=0 next_free=0")

    # --- C3: Zero FAT1 entries for readme.txt and docs/notes.txt ---
    if 'README.TXT' in file_map:
        name, info = file_map['README.TXT']
        chain = info['chain']
        if len(chain) >= 4:
            for idx in range(1, len(chain) - 1, 2):
                c = chain[idx]
                set_fat(img, p, c, 0, fat_num=1)
                print("C3: FAT1[{}]=0 [{}]".format(c, name))

    if 'NOTES.TXT' in file_map:
        name, info = file_map['NOTES.TXT']
        chain = info['chain']
        if len(chain) >= 3:
            mid = len(chain) // 2
            c = chain[mid]
            set_fat(img, p, c, 0, fat_num=1)
            print("C3: FAT1[{}]=0 [{}]".format(c, name))

    # --- C4: Zero FAT2 entries for data.bin and logs/access.log ---
    if 'DATA.BIN' in file_map:
        name, info = file_map['DATA.BIN']
        chain = info['chain']
        if len(chain) >= 4:
            for idx in range(2, len(chain) - 1, 3):
                c = chain[idx]
                set_fat(img, p, c, 0, fat_num=2)
                print("C4: FAT2[{}]=0 [{}]".format(c, name))

    if 'ACCESS.LOG' in file_map:
        name, info = file_map['ACCESS.LOG']
        chain = info['chain']
        if len(chain) >= 4:
            for idx in range(3, len(chain) - 1, 4):
                c = chain[idx]
                set_fat(img, p, c, 0, fat_num=2)
                print("C4: FAT2[{}]=0 [{}]".format(c, name))

    # --- C5: Conflicting non-zero entries ---
    # Find free clusters to use as wrong targets
    free = find_free_clusters(img, p, 6, used)

    # report.csv: FAT1 gets wrong value at chain[7], FAT2 stays correct
    if 'REPORT.CSV' in file_map:
        name, info = file_map['REPORT.CSV']
        chain = info['chain']
        if len(chain) >= 10:
            c = chain[7]
            correct = fat_entry(img, p, c, fat_num=1)
            set_fat(img, p, c, free[0], fat_num=1)
            print("C5: FAT1[{}]={} (wrong, correct={}) [{}]".format(
                c, free[0], correct, name))

    # data.bin: FAT2 gets wrong value at chain[13], FAT1 stays correct
    if 'DATA.BIN' in file_map:
        name, info = file_map['DATA.BIN']
        chain = info['chain']
        if len(chain) >= 15:
            c = chain[13]
            correct = fat_entry(img, p, c, fat_num=2)
            set_fat(img, p, c, free[1], fat_num=2)
            print("C5: FAT2[{}]={} (wrong, correct={}) [{}]".format(
                c, free[1], correct, name))

    # --- C6: Orphaned cluster chain ---
    orphans = find_free_clusters(img, p, 4, used | set(free[:2]), start_from=600)
    for i in range(3):
        set_fat_both(img, p, orphans[i], orphans[i + 1])
    set_fat_both(img, p, orphans[3], 0x0FFFFFF8)
    print("C6: Orphaned chain: {}->{}->{}->{}->EOF".format(*orphans))

    write_img(img, out_path)
    print("Corrupted image written to {}".format(out_path))


if __name__ == '__main__':
    corrupt(sys.argv[1], sys.argv[2])
