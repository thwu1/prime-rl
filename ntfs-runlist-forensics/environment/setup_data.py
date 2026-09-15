#!/usr/bin/env python3
"""
Generate synthetic NTFS disk recovery challenge data.

Creates a raw disk capture containing an NTFS boot sector and multiple MFT
records at various offsets, simulating a forensic recovery scenario after a
failed ntfsresize operation. Includes deceptive candidates: one with overlapping
extents, and one that passes all standard checks but has MFT start LCN
inconsistent with the boot sector.
"""
import struct
import json
import os
import sys

# --- Filesystem parameters ---
BYTES_PER_SECTOR = 512
SECTORS_PER_CLUSTER = 8
CLUSTER_SIZE = BYTES_PER_SECTOR * SECTORS_PER_CLUSTER  # 4096
MFT_ENTRY_SIZE = 1024
MFT_LCN = 0x30000
MFTMIRR_LCN = 0x206733

ORIGINAL_TOTAL_SECTORS = 658505728   # ~314 GiB
RESIZED_TOTAL_SECTORS = 209715200    # ~100 GiB

EXPECTED_MFT_CLUSTERS = 0x7800      # 30720
EXPECTED_FILE_SIZE = EXPECTED_MFT_CLUSTERS * CLUSTER_SIZE  # 125829120

# Windows FILETIME timestamps (100ns intervals since 1601-01-01)
TS_MAIN   = 0x01D9A5B2C0000000  # Filesystem under repair
TS_OTHER1 = 0x01D4B2E5C0000000  # Different filesystem #1
TS_OTHER2 = 0x01D6C1A3B0000000  # Different filesystem #2

# --- Runlist definitions: [(length_clusters, absolute_lcn), ...] ---
CORRECT_RUNLIST = [
    (0x2800, 0x30000),     # Extent 1: starts at boot sector MFT_LCN
    (0x3200, 0x78000),     # Extent 2: within resized volume
    (0x1E00, 0x2000000),   # Extent 3: BEYOND resized volume boundary
]

CORRUPTED_RUNLIST = [
    (0x2800, 0x30000),     # Only first extent survives truncation
]

# Deceptive: same TS_MAIN, total clusters = 0x7800, but overlapping extents
# Extent 1 ends at LCN 0x32800, Extent 2 starts at 0x32000 — 0x800 overlap
DECEPTIVE_RUNLIST = [
    (0x2800, 0x30000),     # LCN 0x30000 to 0x32800
    (0x3000, 0x32000),     # LCN 0x32000 to 0x35000 — OVERLAPS by 0x800
    (0x2000, 0x2000000),   # LCN 0x2000000
]
# Total: 0x2800 + 0x3000 + 0x2000 = 0x7800 — matches expected but invalid

# Quasi-valid: same TS_MAIN, total clusters = 0x7800, NO overlapping extents,
# BUT first extent starts at LCN 0x40000 instead of boot sector MFT_LCN 0x30000.
# This record is from a volume where MFT was at a different location.
QUASI_VALID_RUNLIST = [
    (0x3000, 0x40000),     # First extent at WRONG LCN (0x40000, not 0x30000)
    (0x2800, 0x80000),     # Second extent
    (0x2000, 0x1F00000),   # Third extent
]
# Total: 0x3000 + 0x2800 + 0x2000 = 0x7800 — matches expected
# No overlapping extents: [0x40000-0x43000), [0x80000-0x82800), [0x1F00000-0x1F02000)

OLD_RUNLIST = [
    (0x2800, 0x30000),
    (0x2000, 0x78000),     # MFT was smaller at this earlier point
]

OTHER1_RUNLIST = [
    (0x1000, 0x50000),
    (0x1000, 0x90000),
]

OTHER2_RUNLIST = [
    (0x3000, 0x200000),
    (0x2000, 0x100000),    # Negative LCN delta (defragmentation)
]

# --- Disk capture layout ---
BOOT_OFFSET      = 0x00000
CORRUPT_OFFSET   = 0x01000
CAND_A_OFFSET    = 0x04000   # Deceptive (appears before correct in scan)
CAND_B_OFFSET    = 0x05000   # Different filesystem #1
CAND_C_OFFSET    = 0x06000   # Same FS, old/smaller runlist
CAND_D_OFFSET    = 0x07000   # Correct
CAND_E_OFFSET    = 0x08000   # Different filesystem #2
CAND_F_OFFSET    = 0x09000   # Quasi-valid (passes standard checks, wrong MFT LCN)
CAPTURE_SIZE     = 0x0C000   # 49152 bytes (extra room beyond last entry)


def _unsigned_bytes(value):
    """Minimum bytes to encode unsigned integer."""
    if value == 0:
        return 1
    return (value.bit_length() + 7) // 8


def _signed_bytes(value):
    """Minimum bytes to encode signed integer in two's complement."""
    if value == 0:
        return 1
    if value > 0:
        return (value.bit_length() + 1 + 7) // 8
    else:
        return ((-value - 1).bit_length() + 1 + 7) // 8


def encode_mapping_pairs(runs):
    """Encode [(length, abs_lcn), ...] into NTFS mapping pairs bytes."""
    result = bytearray()
    prev_lcn = 0
    for length, lcn in runs:
        delta = lcn - prev_lcn
        prev_lcn = lcn
        l_sz = _unsigned_bytes(length)
        d_sz = _signed_bytes(delta)
        result.append((d_sz << 4) | l_sz)
        result.extend(length.to_bytes(l_sz, 'little'))
        result.extend(delta.to_bytes(d_sz, 'little', signed=True))
    result.append(0x00)
    return bytes(result)


def build_mft_entry(timestamp, runlist, file_size=None, logfile_seq=42):
    """Build a synthetic 1024-byte MFT entry for $MFT (record 0)."""
    if file_size is None:
        file_size = sum(l for l, _ in runlist) * CLUSTER_SIZE

    total_mapped = sum(l for l, _ in runlist)
    highest_vcn = total_mapped - 1

    entry = bytearray(MFT_ENTRY_SIZE)

    # MFT entry header
    entry[0:4] = b'FILE'
    struct.pack_into('<H', entry, 0x04, 0x0030)  # USA offset
    struct.pack_into('<H', entry, 0x06, 0x0003)  # USA count
    struct.pack_into('<Q', entry, 0x08, logfile_seq)
    struct.pack_into('<H', entry, 0x10, 0x0001)  # sequence number
    struct.pack_into('<H', entry, 0x12, 0x0001)  # hard link count
    struct.pack_into('<H', entry, 0x14, 0x0038)  # first attribute offset
    struct.pack_into('<H', entry, 0x16, 0x0001)  # flags: IN_USE
    struct.pack_into('<I', entry, 0x1C, MFT_ENTRY_SIZE)  # allocated size
    struct.pack_into('<H', entry, 0x28, 0x0004)  # next attribute ID
    struct.pack_into('<I', entry, 0x2C, 0)       # MFT record number: 0

    pos = 0x38

    # $STANDARD_INFORMATION (type 0x10, resident)
    si_data = bytearray(0x48)
    struct.pack_into('<Q', si_data, 0x00, timestamp)  # creation
    struct.pack_into('<Q', si_data, 0x08, timestamp)  # modification
    struct.pack_into('<Q', si_data, 0x10, timestamp)  # MFT modification
    struct.pack_into('<Q', si_data, 0x18, timestamp)  # access
    struct.pack_into('<I', si_data, 0x20, 0x06)       # HIDDEN | SYSTEM

    si_len = (0x18 + len(si_data) + 7) & ~7
    struct.pack_into('<I', entry, pos, 0x10)
    struct.pack_into('<I', entry, pos + 4, si_len)
    entry[pos + 8] = 0  # resident
    struct.pack_into('<H', entry, pos + 0x0A, 0x18)
    struct.pack_into('<H', entry, pos + 0x0E, 0)
    struct.pack_into('<I', entry, pos + 0x10, len(si_data))
    struct.pack_into('<H', entry, pos + 0x14, 0x18)
    entry[pos + 0x18:pos + 0x18 + len(si_data)] = si_data
    pos += si_len

    # $FILE_NAME (type 0x30, resident)
    fname_utf16 = "$MFT".encode('utf-16-le')
    fn_data = bytearray(0x42 + len(fname_utf16))
    struct.pack_into('<Q', fn_data, 0x00, 0x0005000000000005)
    struct.pack_into('<Q', fn_data, 0x08, timestamp)
    struct.pack_into('<Q', fn_data, 0x10, timestamp)
    struct.pack_into('<Q', fn_data, 0x18, timestamp)
    struct.pack_into('<Q', fn_data, 0x20, timestamp)
    struct.pack_into('<Q', fn_data, 0x28, file_size)
    struct.pack_into('<Q', fn_data, 0x30, file_size)
    struct.pack_into('<I', fn_data, 0x38, 0x06)
    fn_data[0x40] = 4
    fn_data[0x41] = 0x03
    fn_data[0x42:0x42 + len(fname_utf16)] = fname_utf16

    fn_len = (0x18 + len(fn_data) + 7) & ~7
    struct.pack_into('<I', entry, pos, 0x30)
    struct.pack_into('<I', entry, pos + 4, fn_len)
    entry[pos + 8] = 0
    struct.pack_into('<H', entry, pos + 0x0A, 0x18)
    struct.pack_into('<H', entry, pos + 0x0E, 1)
    struct.pack_into('<I', entry, pos + 0x10, len(fn_data))
    struct.pack_into('<H', entry, pos + 0x14, 0x18)
    entry[pos + 0x16] = 1
    entry[pos + 0x18:pos + 0x18 + len(fn_data)] = fn_data
    pos += fn_len

    # $DATA (type 0x80, non-resident)
    mp_bytes = encode_mapping_pairs(runlist)
    mp_offset = 0x40
    data_attr_len = (mp_offset + len(mp_bytes) + 7) & ~7

    struct.pack_into('<I', entry, pos, 0x80)
    struct.pack_into('<I', entry, pos + 4, data_attr_len)
    entry[pos + 8] = 1  # non-resident
    struct.pack_into('<H', entry, pos + 0x0A, mp_offset)
    struct.pack_into('<H', entry, pos + 0x0E, 2)
    struct.pack_into('<Q', entry, pos + 0x10, 0)           # start VCN
    struct.pack_into('<Q', entry, pos + 0x18, highest_vcn) # end VCN
    struct.pack_into('<H', entry, pos + 0x20, mp_offset)
    struct.pack_into('<Q', entry, pos + 0x28, file_size)   # allocated
    struct.pack_into('<Q', entry, pos + 0x30, file_size)   # real
    struct.pack_into('<Q', entry, pos + 0x38, file_size)   # initialized
    entry[pos + mp_offset:pos + mp_offset + len(mp_bytes)] = mp_bytes
    pos += data_attr_len

    # End marker
    struct.pack_into('<I', entry, pos, 0xFFFFFFFF)
    pos += 4
    struct.pack_into('<I', entry, 0x18, pos)

    result = bytes(entry)
    assert result[:4] == b'FILE', "Generated entry missing FILE signature"
    return result


def build_boot_sector(total_sectors, mft_lcn, mftmirr_lcn):
    """Build a synthetic 512-byte NTFS boot sector."""
    bs = bytearray(512)
    bs[0:3] = b'\xEB\x52\x90'
    bs[3:11] = b'NTFS    '
    struct.pack_into('<H', bs, 0x0B, BYTES_PER_SECTOR)
    bs[0x0D] = SECTORS_PER_CLUSTER
    bs[0x15] = 0xF8
    struct.pack_into('<H', bs, 0x18, 0x003F)
    struct.pack_into('<H', bs, 0x1A, 0x00FF)
    struct.pack_into('<I', bs, 0x1C, 0x00385000)
    struct.pack_into('<Q', bs, 0x28, total_sectors)
    struct.pack_into('<Q', bs, 0x30, mft_lcn)
    struct.pack_into('<Q', bs, 0x38, mftmirr_lcn)
    bs[0x40] = 0xF6
    bs[0x44] = 0x01
    struct.pack_into('<Q', bs, 0x48, 0xDEADBEEFCAFE1234)
    struct.pack_into('<H', bs, 0x1FE, 0xAA55)
    return bytes(bs)


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else '/app'
    os.makedirs(outdir, exist_ok=True)

    # Build all components
    boot = build_boot_sector(RESIZED_TOTAL_SECTORS, MFT_LCN, MFTMIRR_LCN)
    corrupted = build_mft_entry(TS_MAIN, CORRUPTED_RUNLIST,
                                file_size=EXPECTED_FILE_SIZE, logfile_seq=42)
    cand_a = build_mft_entry(TS_MAIN, DECEPTIVE_RUNLIST,
                             file_size=EXPECTED_FILE_SIZE, logfile_seq=39)
    cand_b = build_mft_entry(TS_OTHER1, OTHER1_RUNLIST, logfile_seq=15)
    cand_c = build_mft_entry(TS_MAIN, OLD_RUNLIST, logfile_seq=30)
    cand_d = build_mft_entry(TS_MAIN, CORRECT_RUNLIST, logfile_seq=38)
    cand_e = build_mft_entry(TS_OTHER2, OTHER2_RUNLIST, logfile_seq=20)
    cand_f = build_mft_entry(TS_MAIN, QUASI_VALID_RUNLIST,
                             file_size=EXPECTED_FILE_SIZE, logfile_seq=35)

    # Build disk capture — fill with 0xCC (cannot form "FILE" signature)
    capture = bytearray(CAPTURE_SIZE)
    for i in range(CAPTURE_SIZE):
        capture[i] = 0xCC

    # Place boot sector at offset 0, zero-pad remainder of first block
    capture[BOOT_OFFSET:BOOT_OFFSET + len(boot)] = boot
    for i in range(BOOT_OFFSET + len(boot), CORRUPT_OFFSET):
        capture[i] = 0x00

    # Place MFT records at designated offsets
    all_entries = [
        (CORRUPT_OFFSET, corrupted, "corrupted"),
        (CAND_A_OFFSET, cand_a, "deceptive"),
        (CAND_B_OFFSET, cand_b, "other_fs_1"),
        (CAND_C_OFFSET, cand_c, "old_snapshot"),
        (CAND_D_OFFSET, cand_d, "correct"),
        (CAND_E_OFFSET, cand_e, "other_fs_2"),
        (CAND_F_OFFSET, cand_f, "quasi_valid"),
    ]

    for offset, entry, label in all_entries:
        assert offset + len(entry) <= CAPTURE_SIZE, \
            f"Entry '{label}' at 0x{offset:x} exceeds capture size"
        capture[offset:offset + len(entry)] = entry
        # Verify FILE signature was written correctly
        assert capture[offset:offset + 4] == b'FILE', \
            f"Entry '{label}' at 0x{offset:x} missing FILE signature after placement"

    # Write disk capture
    capture_path = os.path.join(outdir, 'disk_capture.raw')
    with open(capture_path, 'wb') as f:
        f.write(bytes(capture))

    # Verify the written file
    with open(capture_path, 'rb') as f:
        verify_data = f.read()
    assert len(verify_data) == CAPTURE_SIZE, \
        f"Written capture size {len(verify_data)} != expected {CAPTURE_SIZE}"
    file_count = 0
    for off in range(0, len(verify_data) - 4, 512):
        if verify_data[off:off + 4] == b'FILE':
            file_count += 1
    expected_file_count = len(all_entries)
    assert file_count == expected_file_count, \
        f"Capture has {file_count} FILE signatures, expected {expected_file_count}"

    # Write recovery parameters (no format details or solution hints)
    params = {
        "filesystem_type": "NTFS",
        "cluster_size_bytes": CLUSTER_SIZE,
        "mft_entry_size_bytes": MFT_ENTRY_SIZE,
        "expected_mft_total_clusters": EXPECTED_MFT_CLUSTERS,
        "original_volume_total_sectors": ORIGINAL_TOTAL_SECTORS,
        "bytes_per_sector": BYTES_PER_SECTOR,
        "sectors_per_cluster": SECTORS_PER_CLUSTER,
    }
    with open(os.path.join(outdir, 'params.json'), 'w') as f:
        json.dump(params, f, indent=2)

    print(f"Disk capture generated: {CAPTURE_SIZE} bytes, "
          f"{file_count} FILE records verified.")


if __name__ == '__main__':
    main()
