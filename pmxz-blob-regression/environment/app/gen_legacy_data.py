#!/usr/bin/env python3

"""Generate legacy process map data files for migration testing.

Creates .pmx files in various historical formats (raw, PMXZ v1, PMXZ v2)
and one corrupted file, simulating production data accumulated over
multiple software versions. This script is self-contained and does not
import from the app's procmap modules.

Run during Docker build to populate /app/data/legacy/.
"""

import struct
import zlib
import os


def generate_procmap(nprocs, nnodes):
    """Generate a process map string mapping ranks to nodes."""
    if nprocs <= 0 or nnodes <= 0:
        raise ValueError("nprocs and nnodes must be positive")
    if nnodes > nprocs:
        raise ValueError("More nodes than processes")

    base_ppn = nprocs // nnodes
    remainder = nprocs % nnodes
    parts = []
    rank = 0
    for node_idx in range(nnodes):
        ppn = base_ppn + (1 if node_idx < remainder else 0)
        ranks = list(range(rank, rank + ppn))
        rank_str = ",".join(str(r) for r in ranks)
        parts.append(f"node{node_idx}:{rank_str}")
        rank += ppn
    return ";".join(parts)


def pack_raw(procmap_str):
    """Pack in raw format: b'raw:' + UTF-8 data."""
    return b"raw:" + procmap_str.encode('utf-8')


def pack_v1(procmap_str):
    """Pack in PMXZ v1: magic(4) + uncompressed_len(4) + zlib_compressed_data.

    v1 predates the version-byte convention. Byte 4 is the MSB of the
    uncompressed length (big-endian uint32), which is 0x00 for all
    practical process map sizes (< 16 MB).
    """
    raw = procmap_str.encode('utf-8')
    compressed = zlib.compress(raw, 6)
    return b"PMXZ" + struct.pack(">I", len(raw)) + compressed


def pack_v2(procmap_str):
    """Pack in PMXZ v2: magic(4) + version(1) + uncompressed_len(4) + zlib_compressed_data.

    v2 added a version byte (value 2) after the magic to enable
    forward-compatible format evolution.
    """
    raw = procmap_str.encode('utf-8')
    compressed = zlib.compress(raw, 6)
    return b"PMXZ" + bytes([2]) + struct.pack(">I", len(raw)) + compressed


def main():
    outdir = "/app/data/legacy"
    os.makedirs(outdir, exist_ok=True)

    # Raw format files (small maps, below the 4096-byte compression threshold)
    raw_specs = [
        (50, 2, "small_50"),
        (200, 4, "medium_200"),
        (500, 8, "medium_500"),
    ]
    for nprocs, nnodes, name in raw_specs:
        pm = generate_procmap(nprocs, nnodes)
        with open(os.path.join(outdir, f"{name}.pmx"), "wb") as f:
            f.write(pack_raw(pm))

    # PMXZ v1 format files (large maps, from the pre-version-byte era)
    v1_specs = [
        (1200, 10, "v1_1200"),
        (3000, 20, "v1_3000"),
        (6000, 40, "v1_6000"),
    ]
    for nprocs, nnodes, name in v1_specs:
        pm = generate_procmap(nprocs, nnodes)
        with open(os.path.join(outdir, f"{name}.pmx"), "wb") as f:
            f.write(pack_v1(pm))

    # PMXZ v2 format files (large maps, from the current version)
    v2_specs = [
        (1500, 12, "v2_1500"),
        (4000, 25, "v2_4000"),
        (8000, 50, "v2_8000"),
    ]
    for nprocs, nnodes, name in v2_specs:
        pm = generate_procmap(nprocs, nnodes)
        with open(os.path.join(outdir, f"{name}.pmx"), "wb") as f:
            f.write(pack_v2(pm))

    # Corrupted file: valid v2 header but garbage compressed payload
    corrupted = (
        b"PMXZ"
        + bytes([2])
        + struct.pack(">I", 1000)
        + b"NOTVALIDZLIBDATA"
    )
    with open(os.path.join(outdir, "corrupted_job.pmx"), "wb") as f:
        f.write(corrupted)

    total = len(raw_specs) + len(v1_specs) + len(v2_specs) + 1
    print(f"Generated {total} legacy data files in {outdir}")


if __name__ == "__main__":
    main()
