
"""Diagnostic script for the process map serialization pipeline.

Exercises serialization and deserialization for various job sizes,
checks for v3 support, and reports on legacy data files.
"""

import sys
import os


def main():
    sys.path.insert(0, '/app')

    from procmap.generator import generate_procmap
    from procmap.serialize import serialize_procmap, deserialize_procmap

    print("=== Process Map Serialization Diagnostic ===\n")

    # Test raw format (small job, should work)
    test_cases_raw = [
        (100, 4, "small job (raw format)"),
        (500, 8, "medium job (raw format)"),
    ]
    for nprocs, nnodes, desc in test_cases_raw:
        try:
            pm = generate_procmap(nprocs, nnodes)
            result = deserialize_procmap(serialize_procmap(pm))
            assert result == pm
            print(f"  PASS: {desc} ({nprocs} procs, {nnodes} nodes)")
        except Exception as e:
            print(f"  FAIL: {desc} ({nprocs} procs, {nnodes} nodes): {e}")

    # Test blob format (large jobs, may fail due to v2 deserialization bug)
    test_cases_blob = [
        (2000, 16, "large job (blob format)"),
        (5000, 32, "very large job (blob format)"),
        (10000, 64, "huge job (blob format)"),
    ]
    for nprocs, nnodes, desc in test_cases_blob:
        try:
            pm = generate_procmap(nprocs, nnodes)
            result = deserialize_procmap(serialize_procmap(pm))
            assert result == pm
            print(f"  PASS: {desc} ({nprocs} procs, {nnodes} nodes)")
        except Exception as e:
            print(f"  FAIL: {desc} ({nprocs} procs, {nnodes} nodes): {e}")

    # Check for v3 support
    print("\n=== Feature Checks ===\n")
    try:
        from procmap.serialize import serialize_procmap_v3
        print("  serialize_procmap_v3: AVAILABLE")
    except ImportError:
        print("  serialize_procmap_v3: NOT IMPLEMENTED")

    # Check for migration tool
    if os.path.isfile("/app/migrate.py"):
        print("  migrate.py:           AVAILABLE")
    else:
        print("  migrate.py:           NOT CREATED")

    # Check legacy data
    print("\n=== Legacy Data ===\n")
    legacy_dir = "/app/data/legacy"
    if os.path.isdir(legacy_dir):
        files = sorted(f for f in os.listdir(legacy_dir) if f.endswith('.pmx'))
        print(f"  {len(files)} .pmx files in {legacy_dir}:")
        for fname in files:
            fpath = os.path.join(legacy_dir, fname)
            size = os.path.getsize(fpath)
            with open(fpath, 'rb') as f:
                header = f.read(5)
            if header[:4] == b"raw:":
                fmt = "raw"
            elif header[:4] == b"PMXZ":
                vb = header[4] if len(header) > 4 else -1
                if 2 <= vb <= 127:
                    fmt = f"v{vb}"
                else:
                    fmt = "v1"
            else:
                fmt = "unknown"
            print(f"    {fname:25s}  {size:>8d} bytes  format={fmt}")
    else:
        print(f"  {legacy_dir} does not exist")

    return 0


if __name__ == "__main__":
    sys.exit(main())
