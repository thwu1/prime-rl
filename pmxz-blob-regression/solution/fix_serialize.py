#!/usr/bin/env python3

"""Diagnose and fix the process map serialization regression.

Analyzes the serialization source code to find format mismatches
between the blob packer and unpacker, then applies the fix and
verifies correctness.
"""

import re
import sys

SERIALIZE_PATH = '/app/procmap/serialize.py'


def analyze_and_fix():
    """Analyze _pack_blob and _unpack_blob for offset mismatches."""
    with open(SERIALIZE_PATH, 'r') as f:
        source = f.read()

    # Extract _pack_blob function body
    pack_match = re.search(
        r'def _pack_blob\(.*?\):\s*\n(.*?)(?=\ndef )',
        source,
        re.DOTALL,
    )
    if not pack_match:
        print("ERROR: Could not find _pack_blob")
        return False

    pack_body = pack_match.group(1)

    # Determine whether _pack_blob writes a version byte
    writes_version = (
        'bytes([' in pack_body
        or 'BLOB_VERSION' in pack_body
        or 'version' in pack_body.lower()
    )

    # Extract _unpack_blob function body
    unpack_match = re.search(
        r'def _unpack_blob\(.*?\):\s*\n(.*?)(?=\ndef |\Z)',
        source,
        re.DOTALL,
    )
    if not unpack_match:
        print("ERROR: Could not find _unpack_blob")
        return False

    unpack_body = unpack_match.group(1)

    # Check if _unpack_blob reads a version byte
    reads_version = 'version' in unpack_body.lower() and 'blob[4]' in unpack_body

    print(f"_pack_blob writes version byte: {writes_version}")
    print(f"_unpack_blob reads version byte: {reads_version}")

    if writes_version and not reads_version:
        print("\nBUG: _pack_blob includes a version byte at offset 4 but "
              "_unpack_blob does not account for it.")
        print("All field offsets in _unpack_blob are shifted by 1 byte.\n")

        # Parse current offsets from _unpack_blob
        len_re = re.search(r'blob\[(\d+):(\d+)\]', unpack_body)
        data_re = re.search(r'blob\[(\d+):\]', unpack_body)

        if not len_re or not data_re:
            print("ERROR: Could not parse offsets")
            return False

        cur_len_start = int(len_re.group(1))
        cur_len_end = int(len_re.group(2))
        cur_data_start = int(data_re.group(1))

        # Correct offsets: shift by 1 for the version byte
        new_len_start = cur_len_start + 1
        new_len_end = cur_len_end + 1
        new_data_start = cur_data_start + 1

        print(f"Current offsets:  length=[{cur_len_start}:{cur_len_end}], "
              f"data=[{cur_data_start}:]")
        print(f"Corrected offsets: length=[{new_len_start}:{new_len_end}], "
              f"data=[{new_data_start}:]")

        # Apply the fix
        old_block = (
            "    # Read uncompressed length from header\n"
            f"    uncompressed_len = struct.unpack(\">I\", blob[{cur_len_start}:{cur_len_end}])[0]\n"
            f"    compressed_data = blob[{cur_data_start}:]"
        )
        new_block = (
            "    # Skip version byte at offset 4, then read uncompressed length\n"
            f"    _version = blob[4]\n"
            f"    uncompressed_len = struct.unpack(\">I\", blob[{new_len_start}:{new_len_end}])[0]\n"
            f"    compressed_data = blob[{new_data_start}:]"
        )

        if old_block not in source:
            print("ERROR: Could not locate the exact code block to patch")
            return False

        patched = source.replace(old_block, new_block)
        with open(SERIALIZE_PATH, 'w') as f:
            f.write(patched)

        print(f"\nPatch applied to {SERIALIZE_PATH}")
        return True
    else:
        print("No version-byte mismatch detected")
        return True


def verify_fix():
    """Verify the fix with round-trip tests across the threshold."""
    # Clear cached modules so the patched code is loaded
    mods = [k for k in sys.modules if k.startswith('procmap') or k == 'config']
    for m in mods:
        del sys.modules[m]

    sys.path.insert(0, '/app')

    from procmap.generator import generate_procmap
    from procmap.serialize import serialize_procmap, deserialize_procmap

    cases = [
        (100, 4, "small / raw"),
        (1030, 9, "below threshold / raw"),
        (1031, 9, "above threshold / blob"),
        (1042, 9, "regression case / blob"),
        (2000, 16, "large / blob"),
        (5000, 32, "very large / blob"),
        (10000, 64, "huge / blob"),
    ]

    all_ok = True
    for nprocs, nnodes, label in cases:
        try:
            pm = generate_procmap(nprocs, nnodes)
            assert deserialize_procmap(serialize_procmap(pm)) == pm
            print(f"  PASS: {label} ({nprocs} procs)")
        except Exception as e:
            print(f"  FAIL: {label} ({nprocs} procs): {e}")
            all_ok = False
    return all_ok


if __name__ == "__main__":
    print("=== Analyzing process map serialization pipeline ===\n")

    if not analyze_and_fix():
        sys.exit(1)

    print("\n=== Verifying fix ===\n")
    if verify_fix():
        print("\nAll round-trip tests passed.")
    else:
        print("\nVerification FAILED.")
        sys.exit(1)
