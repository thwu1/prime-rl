#!/usr/bin/env python3

"""Solution: Fix cross-module version-handling bugs, implement v3 format, build migration tool.

This script:
1. Analyzes serialize.py to confirm the v2 deserialization bug and identify
   the _validate_blob_header forward-compatibility issue
2. Patches _unpack_blob for v1/v2/v3 support with version-detection heuristic
3. Patches _validate_blob_header to accept v3 using the same heuristic
4. Patches get_format_info to return correct per-version metadata
5. Adds serialize_procmap_v3 with CRC32 and multi-algorithm support
6. Patches validate.py to accept v3 with correct metadata
7. Creates /app/migrate.py for batch format migration with sha256 manifest
8. Verifies all changes with round-trip tests
"""

import re
import os
import sys
import struct
import zlib


SERIALIZE_PATH = '/app/procmap/serialize.py'
VALIDATE_PATH = '/app/procmap/validate.py'
MIGRATE_PATH = '/app/migrate.py'


# ── Step 1: Analyze the existing code ──────────────────────────────────────

def analyze_bugs():
    """Programmatically confirm the bugs across serialize.py and validate.py."""
    with open(SERIALIZE_PATH) as f:
        ser_source = f.read()

    # Check _pack_blob writes version byte
    pack_match = re.search(
        r'def _pack_blob\(.*?\):\s*\n(.*?)(?=\ndef )', ser_source, re.DOTALL
    )
    pack_body = pack_match.group(1) if pack_match else ""
    writes_version = 'BLOB_VERSION' in pack_body or 'bytes([' in pack_body

    # Check _unpack_blob reads version byte
    unpack_match = re.search(
        r'def _unpack_blob\(.*?\):\s*\n(.*?)(?=\ndef |\Z)', ser_source, re.DOTALL
    )
    unpack_body = unpack_match.group(1) if unpack_match else ""
    len_offsets = re.search(r'blob\[(\d+):(\d+)\]', unpack_body)
    len_start = int(len_offsets.group(1)) if len_offsets else -1

    print(f"Bug 1 - _pack_blob writes version byte: {writes_version}")
    print(f"Bug 1 - _unpack_blob length offset starts at: {len_start}")
    if writes_version and len_start == 4:
        print("  CONFIRMED: offset mismatch (should be 5 for v2)")

    # Check _validate_blob_header hardcodes max version
    if 'version > BLOB_VERSION' in ser_source:
        print("Bug 2 - _validate_blob_header: hardcodes max version check")
        print("  CONFIRMED: will reject v3 (version 3 > BLOB_VERSION=2)")

    # Check _validate_blob_header is called from _unpack_blob
    if '_validate_blob_header(blob)' in unpack_body or '_validate_blob_header(' in unpack_body:
        print("  _validate_blob_header IS called from _unpack_blob")
    else:
        print("  _validate_blob_header is NOT called from _unpack_blob")

    # Check get_format_info uses hardcoded v2 offsets
    fmt_match = re.search(
        r'def get_format_info\(.*?\):\s*\n(.*?)(?=\ndef )', ser_source, re.DOTALL
    )
    fmt_body = fmt_match.group(1) if fmt_match else ""
    if '"header_size"] = 9' in fmt_body and 'version == 1' not in fmt_body:
        print("Bug 3 - get_format_info: hardcodes header_size=9 for all blobs")
        print("  CONFIRMED: wrong for v1 (header=8) and v3 (header=18)")

    # Check validate.py rejects version > 2
    with open(VALIDATE_PATH) as f:
        val_source = f.read()
    if 'version > 2' in val_source:
        print("Bug 4 - validate_serialized_data: rejects version > 2")
        print("  CONFIRMED: will reject v3 blobs")

    return True


# ── Step 2: Patch serialize.py ─────────────────────────────────────────────

def patch_serialize():
    """Apply all fixes to serialize.py."""
    with open(SERIALIZE_PATH) as f:
        source = f.read()

    # ── 2a: Add imports ──────────────────────────────────────────────────
    if 'import lzma' not in source:
        source = source.replace('import struct', 'import struct\nimport lzma')
    if 'import zlib' not in source:
        source = source.replace('import struct', 'import struct\nimport zlib')
    if 'import zstandard' not in source:
        source = source.replace('import struct', 'import struct\nimport zstandard')

    # ── 2b: Fix _validate_blob_header ────────────────────────────────────
    old_validate = """    version = blob[4]
    if version > BLOB_VERSION:
        raise ValueError(
            f"Unsupported blob version: {version} "
            f"(max supported: {BLOB_VERSION})"
        )"""

    new_validate = """    # Use version-detection heuristic: byte 4 in [2,127] = version, else v1
    version_byte = blob[4]
    if 2 <= version_byte <= 127:
        version = version_byte
    else:
        version = 1
    if version not in (1, 2, 3):
        raise ValueError(
            f"Unsupported blob version: {version}"
        )"""

    if old_validate in source:
        source = source.replace(old_validate, new_validate)
        print("Fixed _validate_blob_header: version-detection heuristic applied")
    else:
        print("WARNING: _validate_blob_header pattern not found")

    # ── 2c: Fix get_format_info ──────────────────────────────────────────
    old_format_info = """    elif fmt == "blob":
        info["magic"] = data[:4].decode('ascii')
        info["version"] = data[4]
        info["header_size"] = 9  # magic(4) + version(1) + length(4)
        info["payload_size"] = len(data) - 9
        uncompressed_len = struct.unpack(">I", data[5:9])[0]
        info["uncompressed_size"] = uncompressed_len
        if uncompressed_len > 0:
            info["compression_ratio"] = info["payload_size"] / uncompressed_len"""

    new_format_info = """    elif fmt == "blob":
        info["magic"] = data[:4].decode('ascii')
        # Version detection heuristic
        vb = data[4]
        if 2 <= vb <= 127:
            version = vb
        else:
            version = 1
        info["version"] = version
        if version == 1:
            info["header_size"] = 8
            info["payload_size"] = len(data) - 8
            uncompressed_len = struct.unpack(">I", data[4:8])[0]
        elif version == 2:
            info["header_size"] = 9
            info["payload_size"] = len(data) - 9
            uncompressed_len = struct.unpack(">I", data[5:9])[0]
        elif version == 3:
            info["header_size"] = 18
            info["payload_size"] = len(data) - 18
            flags = data[5]
            algo_bits = flags & 0x03
            info["algorithm"] = {0: "zlib", 1: "lzma", 2: "zstd"}.get(algo_bits, "unknown")
            info["has_checksum"] = bool(flags & 0x04)
            uncompressed_len = struct.unpack(">I", data[6:10])[0]
            info["crc32"] = struct.unpack(">I", data[10:14])[0]
            info["compressed_len"] = struct.unpack(">I", data[14:18])[0]
        else:
            info["header_size"] = 9
            info["payload_size"] = len(data) - 9
            uncompressed_len = struct.unpack(">I", data[5:9])[0]
        info["uncompressed_size"] = uncompressed_len
        if uncompressed_len > 0:
            info["compression_ratio"] = info["payload_size"] / uncompressed_len"""

    if old_format_info in source:
        source = source.replace(old_format_info, new_format_info)
        print("Fixed get_format_info: per-version metadata")
    else:
        print("WARNING: get_format_info pattern not found")

    # ── 2d: Replace _unpack_blob ─────────────────────────────────────────
    # Find _unpack_blob boundaries
    lines = source.split('\n')
    unpack_start = None
    unpack_end = None
    for i, line in enumerate(lines):
        if 'def _unpack_blob(' in line:
            unpack_start = i
        elif unpack_start is not None and i > unpack_start and \
                re.match(r'^def [a-z_]', line):
            unpack_end = i
            break
    if unpack_start is None:
        print("ERROR: _unpack_blob not found")
        return False
    if unpack_end is None:
        unpack_end = len(lines)

    new_unpack_lines = '''\
def _unpack_blob(blob):
    """Unpack a PMXZ blob (v1, v2, or v3) back to the original process map string.

    Auto-detects format version from byte 4:
      - 2-127: version number (v2, v3, etc.)
      - 0, 1, >127: v1 format (no version byte)

    Args:
        blob: PMXZ blob bytes

    Returns:
        Decoded process map string

    Raises:
        ValueError: If the blob is malformed or CRC32 check fails (v3)
    """
    magic = blob[:4]
    if magic != BLOB_MAGIC_BYTES:
        raise ValueError(f"Invalid blob magic: {magic}")

    _validate_blob_header(blob)

    # Detect version using the heuristic from REQUIREMENTS_V3.md
    version_byte = blob[4]
    if 2 <= version_byte <= 127:
        version = version_byte
    else:
        version = 1

    if version == 1:
        # v1: magic(4) + uncompressed_len(4) + zlib_data
        uncompressed_len = struct.unpack(">I", blob[4:8])[0]
        compressed_data = blob[8:]
        raw_bytes = decompress_data(compressed_data, expected_len=uncompressed_len)

    elif version == 2:
        # v2: magic(4) + version(1) + uncompressed_len(4) + zlib_data
        uncompressed_len = struct.unpack(">I", blob[5:9])[0]
        compressed_data = blob[9:]
        raw_bytes = decompress_data(compressed_data, expected_len=uncompressed_len)

    elif version == 3:
        # v3: magic(4) + version(1) + flags(1) + uncomp_len(4)
        #     + crc32(4) + comp_len(4) + compressed_data
        if len(blob) < 18:
            raise ValueError(
                f"v3 blob too short: {len(blob)} bytes, need >= 18"
            )
        flags = blob[5]
        algo_bits = flags & 0x03
        uncompressed_len = struct.unpack(">I", blob[6:10])[0]
        expected_crc = struct.unpack(">I", blob[10:14])[0]
        comp_len = struct.unpack(">I", blob[14:18])[0]
        compressed_data = blob[18:18 + comp_len]

        if algo_bits == 0:
            raw_bytes = zlib.decompress(compressed_data)
        elif algo_bits == 1:
            raw_bytes = lzma.decompress(compressed_data)
        elif algo_bits == 2:
            dctx = zstandard.ZstdDecompressor()
            raw_bytes = dctx.decompress(compressed_data)
        else:
            raise ValueError(f"Unknown v3 algorithm bits: {algo_bits}")

        if len(raw_bytes) != uncompressed_len:
            raise ValueError(
                f"Decompressed size mismatch: expected {uncompressed_len}, "
                f"got {len(raw_bytes)}"
            )

        actual_crc = zlib.crc32(raw_bytes) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise ValueError(
                f"CRC32 mismatch: expected {expected_crc:#010x}, "
                f"got {actual_crc:#010x}"
            )
    else:
        raise ValueError(f"Unsupported PMXZ version: {version}")

    return raw_bytes.decode('utf-8')

'''.split('\n')

    result_lines = lines[:unpack_start] + new_unpack_lines + lines[unpack_end:]
    source = '\n'.join(result_lines)
    print(f"Replaced _unpack_blob (lines {unpack_start+1}..{unpack_end})")

    # ── 2e: Add serialize_procmap_v3 at end ──────────────────────────────
    v3_func = '''

def serialize_procmap_v3(procmap_str, algorithm='zlib'):
    """Serialize a process map in PMXZ v3 format.

    Always produces a v3 blob regardless of data size.

    v3 header (18 bytes):
        magic(4) + version(1) + flags(1) + uncomp_len(4) +
        crc32(4) + comp_len(4)

    Flags byte:
        bits 0-1: algorithm (0=zlib, 1=lzma, 2=zstd)
        bit 2:    checksummed (always 1 for v3)
        bits 3-7: reserved (0)

    Args:
        procmap_str: Process map string
        algorithm: 'zlib' (default), 'lzma', or 'zstd'

    Returns:
        PMXZ v3 format bytes

    Raises:
        ValueError: If algorithm is not supported
    """
    raw_bytes = procmap_str.encode('utf-8')

    # CRC32 of uncompressed data
    crc = zlib.crc32(raw_bytes) & 0xFFFFFFFF

    # Compress with selected algorithm
    if algorithm == 'zlib':
        compressed = zlib.compress(raw_bytes, 6)
        algo_bits = 0
    elif algorithm == 'lzma':
        compressed = lzma.compress(raw_bytes)
        algo_bits = 1
    elif algorithm == 'zstd':
        cctx = zstandard.ZstdCompressor()
        compressed = cctx.compress(raw_bytes)
        algo_bits = 2
    else:
        raise ValueError(f"Unsupported compression algorithm: {algorithm}")

    # Flags: bits 0-1 = algorithm, bit 2 = checksummed
    flags = algo_bits | 0x04

    # Build 18-byte header
    header = struct.pack(
        ">4sBBIII",
        BLOB_MAGIC_BYTES,    # magic  (4 bytes)
        3,                    # version (1 byte)
        flags,                # flags   (1 byte)
        len(raw_bytes),       # uncompressed length (4 bytes)
        crc,                  # CRC32   (4 bytes)
        len(compressed),      # compressed length   (4 bytes)
    )

    return header + compressed
'''

    source += v3_func
    print("Added serialize_procmap_v3")

    with open(SERIALIZE_PATH, 'w') as f:
        f.write(source)
    print(f"Wrote patched {SERIALIZE_PATH}")
    return True


# ── Step 3: Patch validate.py ────────────────────────────────────────────

def patch_validate():
    """Fix validate_serialized_data to accept v3 and use version heuristic."""
    with open(VALIDATE_PATH) as f:
        source = f.read()

    old_blob_section = '''    elif data[:4] == b"PMXZ":
        if len(data) < 9:
            raise ValueError(
                f"Blob too short for header: {len(data)} bytes, need >= 9"
            )
        version = data[4]
        if version > 2:
            raise ValueError(f"Unsupported blob version: {version}")
        return {
            "format": "blob",
            "version": version,
            "payload_size": len(data) - 9,
        }'''

    new_blob_section = '''    elif data[:4] == b"PMXZ":
        if len(data) < 8:
            raise ValueError(
                f"Blob too short for header: {len(data)} bytes, need >= 8"
            )
        # Version detection heuristic: byte 4 in [2,127] = version, else v1
        vb = data[4]
        if 2 <= vb <= 127:
            version = vb
        else:
            version = 1
        if version == 1:
            header_size = 8
        elif version == 2:
            header_size = 9
        elif version == 3:
            if len(data) < 18:
                raise ValueError(
                    f"v3 blob too short: {len(data)} bytes, need >= 18"
                )
            header_size = 18
        else:
            raise ValueError(f"Unsupported blob version: {version}")
        return {
            "format": "blob",
            "version": version,
            "payload_size": len(data) - header_size,
        }'''

    if old_blob_section in source:
        source = source.replace(old_blob_section, new_blob_section)
        with open(VALIDATE_PATH, 'w') as f:
            f.write(source)
        print(f"Fixed {VALIDATE_PATH}: version-detection heuristic applied")
        return True
    else:
        print(f"WARNING: validate_serialized_data pattern not found in {VALIDATE_PATH}")
        return False


# ── Step 4: Create migration tool ────────────────────────────────────────

def create_migration_tool():
    """Create /app/migrate.py CLI tool."""
    code = '''#!/usr/bin/env python3
"""CLI migration tool: converts .pmx files to PMXZ v3 format.

Usage: python3 migrate.py <directory>

Reads every .pmx file in <directory>, detects its format (raw, v1, v2, v3),
re-serializes as v3, overwrites in-place, and writes:
  - <directory>/migration_report.json (structured report)
  - <directory>/migration_checksums.sha256 (sha256sum-compatible manifest)
"""

import os
import sys
import json
import struct
import hashlib

sys.path.insert(0, '/app')

from procmap.serialize import deserialize_procmap, serialize_procmap_v3


def detect_source_format(data):
    """Detect the serialization format of a .pmx file."""
    if len(data) < 4:
        raise ValueError("Data too short to detect format")
    if data[:4] == b"raw:":
        return "raw"
    if data[:4] == b"PMXZ":
        if len(data) < 5:
            raise ValueError("PMXZ blob truncated")
        vb = data[4]
        if 2 <= vb <= 127:
            if vb == 3:
                return "v3"
            elif vb == 2:
                return "v2"
            else:
                return f"v{vb}"
        else:
            return "v1"
    raise ValueError(f"Unknown format magic: {data[:4].hex()}")


def migrate_directory(directory):
    """Migrate all .pmx files in a directory to v3 format."""
    report = {
        "total_files": 0,
        "migrated": 0,
        "errors": 0,
        "by_source_format": {},
        "error_files": [],
    }

    pmx_files = sorted(f for f in os.listdir(directory) if f.endswith(".pmx"))
    report["total_files"] = len(pmx_files)

    migrated_files = []

    for fname in pmx_files:
        path = os.path.join(directory, fname)
        try:
            with open(path, "rb") as f:
                data = f.read()

            fmt = detect_source_format(data)

            # Already v3 — count but skip conversion
            if fmt == "v3":
                report["migrated"] += 1
                report["by_source_format"]["v3"] = \\
                    report["by_source_format"].get("v3", 0) + 1
                migrated_files.append(fname)
                continue

            # Deserialize from legacy format
            procmap_str = deserialize_procmap(data)

            # Re-serialize as v3
            v3_data = serialize_procmap_v3(procmap_str, algorithm="zlib")

            # Verify round-trip integrity before overwriting
            verify_str = deserialize_procmap(v3_data)
            if verify_str != procmap_str:
                raise ValueError("Round-trip verification failed after v3 conversion")

            # Overwrite with v3 data
            with open(path, "wb") as f:
                f.write(v3_data)

            report["migrated"] += 1
            report["by_source_format"][fmt] = \\
                report["by_source_format"].get(fmt, 0) + 1
            migrated_files.append(fname)

        except Exception as e:
            report["errors"] += 1
            report["error_files"].append(fname)

    # Write JSON report
    report_path = os.path.join(directory, "migration_report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    # Write SHA-256 checksums manifest (sha256sum-compatible format)
    checksums_lines = []
    for fname in sorted(migrated_files):
        path = os.path.join(directory, fname)
        with open(path, "rb") as fh:
            sha = hashlib.sha256(fh.read()).hexdigest()
        checksums_lines.append(f"{sha}  {fname}")

    checksums_path = os.path.join(directory, "migration_checksums.sha256")
    with open(checksums_path, "w") as f:
        f.write("\\n".join(checksums_lines) + "\\n")

    return report


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <directory>", file=sys.stderr)
        sys.exit(1)

    directory = sys.argv[1]
    if not os.path.isdir(directory):
        print(f"Error: {directory} is not a directory", file=sys.stderr)
        sys.exit(1)

    report = migrate_directory(directory)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
'''
    with open(MIGRATE_PATH, 'w') as f:
        f.write(code)
    os.chmod(MIGRATE_PATH, 0o755)
    print(f"Created {MIGRATE_PATH}")


# ── Step 5: Verify everything ────────────────────────────────────────────

def verify():
    """Run verification tests."""
    # Clear cached modules so patched code is loaded fresh
    to_clear = [k for k in sys.modules if k.startswith('procmap') or k == 'config']
    for m in to_clear:
        del sys.modules[m]

    sys.path.insert(0, '/app')
    from procmap.generator import generate_procmap
    from procmap.serialize import (
        serialize_procmap, deserialize_procmap, serialize_procmap_v3,
        get_format_info
    )
    from procmap.validate import validate_serialized_data

    ok = True

    # v2 round-trip (bug fix verification)
    print("\n--- v2 round-trip ---")
    for nprocs, nnodes in [(1042, 9), (1500, 10), (5000, 32), (10000, 64)]:
        pm = generate_procmap(nprocs, nnodes)
        try:
            assert deserialize_procmap(serialize_procmap(pm)) == pm
            print(f"  PASS: v2 {nprocs} procs")
        except Exception as e:
            print(f"  FAIL: v2 {nprocs} procs: {e}")
            ok = False

    # v1 backward compat
    print("\n--- v1 backward compat ---")
    for nprocs, nnodes in [(2000, 16), (5000, 32)]:
        pm = generate_procmap(nprocs, nnodes)
        raw = pm.encode('utf-8')
        v1_blob = b"PMXZ" + struct.pack(">I", len(raw)) + zlib.compress(raw, 6)
        try:
            assert deserialize_procmap(v1_blob) == pm
            print(f"  PASS: v1 {nprocs} procs")
        except Exception as e:
            print(f"  FAIL: v1 {nprocs} procs: {e}")
            ok = False

    # get_format_info v1
    print("\n--- get_format_info ---")
    pm = generate_procmap(2000, 16)
    raw = pm.encode('utf-8')
    v1_blob = b"PMXZ" + struct.pack(">I", len(raw)) + zlib.compress(raw, 6)
    info = get_format_info(v1_blob)
    if info["version"] == 1 and info["header_size"] == 8:
        print("  PASS: v1 format info correct")
    else:
        print(f"  FAIL: v1 format info: {info}")
        ok = False

    v2_blob = b"PMXZ" + bytes([2]) + struct.pack(">I", len(raw)) + zlib.compress(raw, 6)
    info = get_format_info(v2_blob)
    if info["version"] == 2 and info["header_size"] == 9:
        print("  PASS: v2 format info correct")
    else:
        print(f"  FAIL: v2 format info: {info}")
        ok = False

    # validate_serialized_data v1
    print("\n--- validate_serialized_data ---")
    result = validate_serialized_data(v1_blob)
    if result["version"] == 1:
        print("  PASS: v1 validation correct")
    else:
        print(f"  FAIL: v1 validation: {result}")
        ok = False

    # v3 zlib round-trip
    print("\n--- v3 zlib round-trip ---")
    for nprocs, nnodes in [(100, 4), (1000, 10), (5000, 32), (10000, 64)]:
        pm = generate_procmap(nprocs, nnodes)
        try:
            data = serialize_procmap_v3(pm, algorithm='zlib')
            assert data[:4] == b"PMXZ"
            assert data[4] == 3
            assert deserialize_procmap(data) == pm
            print(f"  PASS: v3/zlib {nprocs} procs")
        except Exception as e:
            print(f"  FAIL: v3/zlib {nprocs} procs: {e}")
            ok = False

    # v3 lzma round-trip
    print("\n--- v3 lzma round-trip ---")
    for nprocs, nnodes in [(100, 4), (5000, 32)]:
        pm = generate_procmap(nprocs, nnodes)
        try:
            data = serialize_procmap_v3(pm, algorithm='lzma')
            assert (data[5] & 0x03) == 1
            assert deserialize_procmap(data) == pm
            print(f"  PASS: v3/lzma {nprocs} procs")
        except Exception as e:
            print(f"  FAIL: v3/lzma {nprocs} procs: {e}")
            ok = False

    # v3 zstd round-trip
    print("\n--- v3 zstd round-trip ---")
    for nprocs, nnodes in [(100, 4), (5000, 32)]:
        pm = generate_procmap(nprocs, nnodes)
        try:
            data = serialize_procmap_v3(pm, algorithm='zstd')
            assert (data[5] & 0x03) == 2
            assert deserialize_procmap(data) == pm
            print(f"  PASS: v3/zstd {nprocs} procs")
        except Exception as e:
            print(f"  FAIL: v3/zstd {nprocs} procs: {e}")
            ok = False

    # v3 format info
    pm = generate_procmap(2000, 16)
    v3_blob = serialize_procmap_v3(pm)
    info = get_format_info(v3_blob)
    if info["version"] == 3 and info["header_size"] == 18:
        print("  PASS: v3 format info correct")
    else:
        print(f"  FAIL: v3 format info: {info}")
        ok = False

    # v3 validate
    result = validate_serialized_data(v3_blob)
    if result["version"] == 3:
        print("  PASS: v3 validation accepted")
    else:
        print(f"  FAIL: v3 validation: {result}")
        ok = False

    # CRC32 tamper detection
    print("\n--- CRC32 integrity ---")
    pm = generate_procmap(1000, 10)
    data = serialize_procmap_v3(pm)
    tampered = bytearray(data)
    tampered[12] ^= 0xFF
    try:
        deserialize_procmap(bytes(tampered))
        print("  FAIL: tampered data should have raised ValueError")
        ok = False
    except ValueError as e:
        if 'CRC32' in str(e) or 'crc32' in str(e).lower():
            print("  PASS: CRC32 mismatch detected")
        else:
            print(f"  FAIL: wrong error message: {e}")
            ok = False
    except Exception as e:
        print(f"  FAIL: unexpected exception type: {type(e).__name__}: {e}")
        ok = False

    if ok:
        print("\nAll verifications passed.")
    else:
        print("\nSome verifications FAILED.")
        sys.exit(1)


# ── Main ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("Step 1: Analyze bugs across modules")
    print("=" * 60)
    analyze_bugs()

    print()
    print("=" * 60)
    print("Step 2: Patch serialize.py")
    print("=" * 60)
    if not patch_serialize():
        sys.exit(1)

    print()
    print("=" * 60)
    print("Step 3: Patch validate.py")
    print("=" * 60)
    if not patch_validate():
        sys.exit(1)

    print()
    print("=" * 60)
    print("Step 4: Create migration tool")
    print("=" * 60)
    create_migration_tool()

    print()
    print("=" * 60)
    print("Step 5: Verify")
    print("=" * 60)
    verify()
