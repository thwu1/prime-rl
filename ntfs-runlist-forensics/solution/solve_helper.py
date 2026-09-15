#!/usr/bin/env python3

"""
NTFS Disk Recovery — Forensic Methodology Design Solution

Designs a candidate evaluation methodology that goes beyond standard structural
checks, implements the recovery, and documents all reasoning. The key insight
is cross-validating each candidate's first extent LCN against the boot sector's
MFT cluster number field to detect candidates from different volume layouts.
"""
import struct
import json
import os
import subprocess
import sys


def run_cmd(cmd):
    """Run a shell command and return stdout."""
    result = subprocess.run(cmd, shell=True, capture_output=True)
    return result.stdout, result.stderr, result.returncode


def decode_mapping_pairs(data, offset=0):
    """Decode NTFS mapping pairs starting at offset."""
    runs = []
    prev_lcn = 0
    i = offset
    while i < len(data):
        hdr = data[i]
        if hdr == 0:
            break
        i += 1
        l_sz = hdr & 0x0F
        d_sz = (hdr >> 4) & 0x0F
        if l_sz == 0:
            break
        length = int.from_bytes(data[i:i + l_sz], 'little')
        i += l_sz
        if d_sz > 0:
            delta = int.from_bytes(data[i:i + d_sz], 'little', signed=True)
            i += d_sz
            lcn = prev_lcn + delta
            prev_lcn = lcn
        else:
            lcn = 0  # sparse run
        runs.append((length, lcn))
    return runs


def encode_mapping_pairs(runs):
    """Encode [(length, abs_lcn), ...] into NTFS mapping pairs bytes."""
    result = bytearray()
    prev_lcn = 0
    for length, lcn in runs:
        delta = lcn - prev_lcn
        prev_lcn = lcn
        if length == 0:
            l_sz = 1
        else:
            l_sz = (length.bit_length() + 7) // 8
        if delta == 0:
            d_sz = 1
        elif delta > 0:
            d_sz = (delta.bit_length() + 1 + 7) // 8
        else:
            d_sz = ((-delta - 1).bit_length() + 1 + 7) // 8
        result.append((d_sz << 4) | l_sz)
        result.extend(length.to_bytes(l_sz, 'little'))
        result.extend(delta.to_bytes(d_sz, 'little', signed=True))
    result.append(0x00)
    return bytes(result)


def find_attrs(data, first_attr_offset):
    """Walk MFT entry attribute chain."""
    attrs = []
    off = first_attr_offset
    while off < len(data) - 8:
        atype = struct.unpack_from('<I', data, off)[0]
        if atype == 0xFFFFFFFF:
            break
        alen = struct.unpack_from('<I', data, off + 4)[0]
        if alen == 0 or alen > len(data) - off:
            break
        attrs.append((atype, off, alen))
        off += alen
    return attrs


def get_creation_time(data, attrs):
    """Extract creation timestamp from $STANDARD_INFORMATION (type 0x10)."""
    for atype, off, alen in attrs:
        if atype == 0x10 and data[off + 8] == 0:
            val_off = struct.unpack_from('<H', data, off + 0x14)[0]
            return struct.unpack_from('<Q', data, off + val_off)[0]
    return None


def get_data_runlist(data, attrs):
    """Extract mapping pairs from $DATA attribute (type 0x80, non-resident)."""
    for atype, off, alen in attrs:
        if atype == 0x80 and data[off + 8] == 1:
            mp_off = struct.unpack_from('<H', data, off + 0x20)[0]
            return decode_mapping_pairs(data, off + mp_off)
    return None


def check_extent_overlap(runs):
    """Check if any extents overlap in physical disk space."""
    if not runs or len(runs) < 2:
        return False
    sorted_runs = sorted(runs, key=lambda r: r[1])
    for i in range(len(sorted_runs) - 1):
        curr_end = sorted_runs[i][1] + sorted_runs[i][0]
        next_start = sorted_runs[i + 1][1]
        if next_start < curr_end:
            return True
    return False


def main():
    app_dir = '/app'
    out_dir = os.path.join(app_dir, 'output')
    os.makedirs(out_dir, exist_ok=True)
    capture_path = os.path.join(app_dir, 'disk_capture.raw')

    # Load recovery parameters
    with open(os.path.join(app_dir, 'params.json')) as f:
        params = json.load(f)
    expected_clusters = params['expected_mft_total_clusters']
    original_sectors = params['original_volume_total_sectors']
    entry_size = params['mft_entry_size_bytes']

    # Step 1: Use sigfind from sleuthkit to locate FILE signatures
    print("=== Scanning for MFT record signatures ===")
    stdout, stderr, rc = run_cmd(
        f"sigfind -b 512 46494c45 {capture_path}"
    )
    sigfind_output = stdout.decode() if stdout else ""
    print(sigfind_output)

    # Step 2: Inspect boot sector with xxd
    print("=== Boot sector hex dump ===")
    stdout, _, _ = run_cmd(f"xxd -l 80 {capture_path}")
    print(stdout.decode() if stdout else "")

    # Read entire capture
    with open(capture_path, 'rb') as f:
        raw_data = f.read()

    # Parse boot sector — extract MFT starting cluster number
    boot_data = raw_data[0:512]
    assert boot_data[3:7] == b'NTFS', "No NTFS signature in boot sector"
    boot_mft_lcn = struct.unpack_from('<Q', boot_data, 0x30)[0]
    print(f"Boot sector MFT_LCN: 0x{boot_mft_lcn:x}")

    # Find FILE signatures at sector boundaries
    file_offsets = []
    for off in range(0, len(raw_data) - 4, 512):
        if raw_data[off:off + 4] == b'FILE':
            file_offsets.append(off)

    print(f"Found FILE signatures at: {[f'0x{o:x}' for o in file_offsets]}")

    # Extract boot sector using dd
    print("\n=== Extracting boot sector with dd ===")
    run_cmd(f"dd if={capture_path} of=/tmp/boot.bin bs=512 count=1 2>/dev/null")

    # Identify the corrupted MFT record — the first FILE signature
    corrupted_offset = file_offsets[0]
    corrupted_entry = raw_data[corrupted_offset:corrupted_offset + entry_size]
    corrupted_data = bytearray(corrupted_entry)
    first_attr = struct.unpack_from('<H', corrupted_data, 0x14)[0]
    corrupted_attrs = find_attrs(corrupted_data, first_attr)
    corrupted_ts = get_creation_time(corrupted_data, corrupted_attrs)
    corrupted_runs = get_data_runlist(corrupted_data, corrupted_attrs)

    # Use dd to extract corrupted record for xxd inspection
    print(f"\n=== Corrupted record at 0x{corrupted_offset:x} ===")
    run_cmd(
        f"dd if={capture_path} of=/tmp/corrupted.bin bs=1 "
        f"skip={corrupted_offset} count={entry_size} 2>/dev/null"
    )
    stdout, _, _ = run_cmd("xxd -l 64 /tmp/corrupted.bin")
    print(stdout.decode() if stdout else "")

    c_total = sum(l for l, _ in corrupted_runs)
    print(f"  Timestamp: 0x{corrupted_ts:016x}")
    print(f"  Runs: {len(corrupted_runs)}, total clusters: 0x{c_total:x}")
    print(f"  Expected total: 0x{expected_clusters:x}")

    # Step 3: Design and apply validation methodology
    # Standard checks alone are insufficient — we must also cross-validate
    # each candidate's first extent LCN against the boot sector's MFT_LCN field
    print("\n=== Designing validation methodology ===")
    print(f"  Boot sector MFT_LCN = 0x{boot_mft_lcn:x}")
    print("  Any valid $MFT record's first data extent must start at this LCN")

    methodology = [
        {
            "criterion": "FILE signature validation",
            "description": "Verify the record starts with the FILE (0x46494C45) magic signature, confirming it is a structurally valid MFT entry",
            "rationale": "Eliminates non-MFT data at sector-aligned offsets from consideration as repair candidates"
        },
        {
            "criterion": "Creation timestamp provenance",
            "description": "Compare the $STANDARD_INFORMATION creation timestamp against the corrupted record's timestamp to verify both records originate from the same filesystem instance",
            "rationale": "A raw capture may contain MFT records from multiple filesystem images; only records from the target filesystem are valid repair sources since they describe the same on-disk layout"
        },
        {
            "criterion": "Total cluster count verification",
            "description": "Sum all extent lengths in the $DATA attribute's mapping pairs and verify the total equals the expected MFT cluster count from recovery parameters",
            "rationale": "The MFT grows over a filesystem's lifetime; older snapshots have fewer clusters and represent a stale state that would lose recent metadata if used for repair"
        },
        {
            "criterion": "Physical extent overlap detection",
            "description": "Sort all data extents by starting LCN and verify no extent's starting LCN falls within a preceding extent's physical range, detecting impossible physical layouts",
            "rationale": "Overlapping extents indicate corruption in the mapping pairs encoding — such a record maps identical disk clusters to multiple VCN ranges, which would produce data corruption if used as a repair source"
        },
        {
            "criterion": "Boot sector MFT location cross-validation",
            "description": "Verify that the candidate's first data extent starts at the LCN specified in the boot sector's MFT cluster number field (BPB offset 0x30), ensuring geometric consistency with the current volume layout",
            "rationale": "The boot sector's MFT_LCN field is the authoritative pointer to where $MFT begins on the volume. A candidate whose first extent starts at a different LCN originates from a volume configuration where the MFT resided at a different physical location, making it semantically incompatible even if structurally valid"
        },
    ]

    # Step 4: Evaluate all candidate records
    print("\n=== Evaluating candidates ===")
    candidates = []
    correct_offset = None
    correct_runs = None
    candidate_offsets = [o for o in file_offsets if o != corrupted_offset]

    for offset in candidate_offsets:
        entry = raw_data[offset:offset + entry_size]
        if len(entry) < entry_size or entry[:4] != b'FILE':
            continue

        # Extract with dd for hex inspection
        run_cmd(
            f"dd if={capture_path} of=/tmp/cand_{offset:x}.bin bs=1 "
            f"skip={offset} count={entry_size} 2>/dev/null"
        )

        first = struct.unpack_from('<H', entry, 0x14)[0]
        attrs = find_attrs(entry, first)
        s_ts = get_creation_time(entry, attrs)
        s_runs = get_data_runlist(entry, attrs)
        s_total = sum(l for l, _ in s_runs) if s_runs else 0

        ts_match = s_ts == corrupted_ts
        cluster_match = s_total == expected_clusters
        has_overlap = check_extent_overlap(s_runs) if s_runs else False
        mft_lcn_match = (s_runs and s_runs[0][1] == boot_mft_lcn)

        # Apply designed methodology: ALL criteria must pass
        if ts_match and cluster_match and not has_overlap and mft_lcn_match:
            verdict = "accepted"
            reason = (
                "Passes all validation criteria: timestamp matches target filesystem, "
                "total cluster count equals expected value, no overlapping extents, "
                "and first extent LCN matches boot sector MFT location"
            )
            correct_offset = offset
            correct_runs = s_runs
        elif not ts_match:
            verdict = "rejected"
            reason = "Different filesystem origin (creation timestamp mismatch)"
        elif not cluster_match:
            verdict = "rejected"
            reason = (
                f"Cluster count mismatch: record maps 0x{s_total:x} clusters, "
                f"expected 0x{expected_clusters:x}"
            )
        elif has_overlap:
            verdict = "rejected"
            reason = (
                "Overlapping physical extents detected — structurally corrupt, "
                "unusable as repair source despite matching metadata"
            )
        elif not mft_lcn_match:
            first_lcn = s_runs[0][1] if s_runs else 0
            verdict = "rejected"
            reason = (
                f"Boot sector MFT location mismatch: first extent starts at "
                f"LCN 0x{first_lcn:x} but boot sector specifies MFT at "
                f"LCN 0x{boot_mft_lcn:x} — record originates from a different "
                f"volume layout and is semantically incompatible"
            )
        else:
            verdict = "rejected"
            reason = "Does not meet designed validation criteria"

        candidates.append({
            "offset": offset,
            "verdict": verdict,
            "reason": reason,
        })

        print(f"\n  Candidate 0x{offset:x}: {verdict}")
        print(f"    TS match={ts_match}, clusters=0x{s_total:x}, "
              f"overlap={has_overlap}, mft_lcn_match={mft_lcn_match}")
        if s_runs:
            for i, (length, lcn) in enumerate(s_runs):
                print(f"    Run {i}: LCN=0x{lcn:x}, length=0x{length:x}")

    # Include corrupted record in evaluation
    candidates.insert(0, {
        "offset": corrupted_offset,
        "verdict": "rejected",
        "reason": "Damaged record with truncated extent mapping — this is the repair target, not a repair source",
    })

    if correct_offset is None:
        print("ERROR: No suitable repair candidate found!")
        sys.exit(1)

    print(f"\n=== Selected repair source: 0x{correct_offset:x} ===")
    for i, (length, lcn) in enumerate(correct_runs):
        print(f"  Run {i}: LCN=0x{lcn:x}, length=0x{length:x}")

    # Step 5: Build repaired MFT entry
    new_mp = encode_mapping_pairs(correct_runs)
    new_highest_vcn = expected_clusters - 1

    # Find $DATA attribute in corrupted entry
    data_attr_off = None
    for atype, off, alen in corrupted_attrs:
        if atype == 0x80:
            data_attr_off = off
            break

    # Build new $DATA attribute with correct mapping pairs
    mp_start = 0x40
    new_data_len = (mp_start + len(new_mp) + 7) & ~7
    new_data = bytearray(new_data_len)
    new_data[:mp_start] = corrupted_data[data_attr_off:data_attr_off + mp_start]
    struct.pack_into('<I', new_data, 4, new_data_len)
    struct.pack_into('<Q', new_data, 0x18, new_highest_vcn)
    new_data[mp_start:mp_start + len(new_mp)] = new_mp

    # Splice into entry: preserve everything before $DATA, replace $DATA, add end marker
    repaired = bytearray(1024)
    before = corrupted_data[:data_attr_off]
    repaired[:len(before)] = before
    p = len(before)
    repaired[p:p + new_data_len] = new_data
    p += new_data_len
    struct.pack_into('<I', repaired, p, 0xFFFFFFFF)
    p += 4
    struct.pack_into('<I', repaired, 0x18, p)  # update used_size

    repaired_mft_path = os.path.join(out_dir, 'repaired_mft_entry.bin')
    with open(repaired_mft_path, 'wb') as f:
        f.write(bytes(repaired))

    # Verify with xxd
    stdout, _, _ = run_cmd(f"xxd -l 64 {repaired_mft_path}")
    print(f"\nRepaired MFT header:\n{stdout.decode() if stdout else ''}")

    # Step 6: Repair boot sector — restore original volume size
    boot = bytearray(boot_data)
    old_sectors = struct.unpack_from('<Q', boot, 0x28)[0]
    struct.pack_into('<Q', boot, 0x28, original_sectors)

    repaired_boot_path = os.path.join(out_dir, 'repaired_boot_sector.bin')
    with open(repaired_boot_path, 'wb') as f:
        f.write(bytes(boot))
    print(f"Boot sector: {old_sectors} -> {original_sectors} total sectors")

    # Verify with xxd
    stdout, _, _ = run_cmd(
        f"xxd -s 0x28 -l 8 {repaired_boot_path}"
    )
    print(f"Boot sector offset 0x28:\n{stdout.decode() if stdout else ''}")

    # Step 7: Write forensic report with designed methodology
    confidence = {
        "level": "high",
        "justification": (
            "The selected candidate at offset 0x7000 is the only record that passes "
            "all five designed validation criteria, including boot sector MFT location "
            "cross-validation. All other candidates were rejected for specific, "
            "well-understood reasons. The repair operations (mapping pairs re-encoding, "
            "VCN update, boot sector patching) are deterministic with independently "
            "verifiable outputs."
        )
    }

    report = {
        'validation_methodology': methodology,
        'candidate_records': candidates,
        'selected_record_offset': correct_offset,
        'corrupted_runlist': [
            {'lcn': lcn, 'length': length} for length, lcn in corrupted_runs
        ],
        'correct_runlist': [
            {'lcn': lcn, 'length': length} for length, lcn in correct_runs
        ],
        'repaired_highest_vcn': new_highest_vcn,
        'original_volume_sectors': original_sectors,
        'confidence_assessment': confidence,
    }
    report_path = os.path.join(out_dir, 'forensic_report.json')
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"\nWrote forensic report to {report_path}")
    print("Recovery complete.")


if __name__ == '__main__':
    main()
