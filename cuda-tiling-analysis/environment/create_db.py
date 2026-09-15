#!/usr/bin/env python3
"""Create the gpu_specs.db SQLite database with GPU architecture specifications."""

import sqlite3
import sys

db_path = sys.argv[1] if len(sys.argv) > 1 else "/app/gpu_specs.db"
conn = sqlite3.connect(db_path)
c = conn.cursor()

c.execute("""
CREATE TABLE gpu_specs (
    gpu_name TEXT NOT NULL,
    spec_key TEXT NOT NULL,
    spec_value TEXT NOT NULL,
    PRIMARY KEY (gpu_name, spec_key)
)
""")

specs = {
    "A6000": [
        ("compute_capability", "8.6"),
        ("max_threads_per_sm", "1536"),
        ("max_warps_per_sm", "48"),
        ("max_blocks_per_sm", "16"),
        ("max_regs_per_sm", "65536"),
        ("max_smem_per_block_bytes", "49152"),
        ("smem_per_sm_bytes", "102400"),
        ("smem_alloc_granularity_bytes", "128"),
        ("reg_alloc_granularity", "256"),
        ("warp_size", "32"),
    ],
    "A100": [
        ("compute_capability", "8.0"),
        ("max_threads_per_sm", "2048"),
        ("max_warps_per_sm", "64"),
        ("max_blocks_per_sm", "32"),
        ("max_regs_per_sm", "65536"),
        ("max_smem_per_block_bytes", "49152"),
        ("smem_per_sm_bytes", "167936"),
        ("smem_alloc_granularity_bytes", "128"),
        ("reg_alloc_granularity", "256"),
        ("warp_size", "32"),
    ],
    "H100": [
        ("compute_capability", "9.0"),
        ("max_threads_per_sm", "2048"),
        ("max_warps_per_sm", "64"),
        ("max_blocks_per_sm", "32"),
        ("max_regs_per_sm", "65536"),
        ("max_smem_per_block_bytes", "49152"),
        ("smem_per_sm_bytes", "233472"),
        ("smem_alloc_granularity_bytes", "128"),
        ("reg_alloc_granularity", "256"),
        ("warp_size", "32"),
    ],
}

for gpu_name, entries in specs.items():
    for key, value in entries:
        c.execute("INSERT INTO gpu_specs VALUES (?, ?, ?)", (gpu_name, key, value))

conn.commit()
conn.close()
print(f"Created {db_path}")
