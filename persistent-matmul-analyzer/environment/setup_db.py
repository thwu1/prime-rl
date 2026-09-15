#!/usr/bin/env python3
"""Create the profiling SQLite database with GPU specs, kernel configs, and workloads."""
import sqlite3
import os

os.makedirs('/app', exist_ok=True)
db_path = '/app/profiling.db'

conn = sqlite3.connect(db_path)
c = conn.cursor()

# GPU hardware specifications (NVIDIA A100-80GB SXM)
c.execute('''CREATE TABLE gpu_specs (
    spec_name TEXT PRIMARY KEY,
    spec_value REAL,
    unit TEXT
)''')
specs = [
    ('num_sms', 108, 'count'),
    ('shared_mem_per_sm', 167936, 'bytes'),
    ('max_shared_mem_per_block', 167936, 'bytes'),
    ('max_warps_per_sm', 64, 'count'),
    ('max_blocks_per_sm', 32, 'count'),
    ('fp16_peak_tflops', 312.0, 'TFLOPS'),
    ('memory_bw_gbps', 2039.0, 'GB/s'),
]
c.executemany('INSERT INTO gpu_specs VALUES (?,?,?)', specs)

# Kernel tuning configurations for persistent matmul
c.execute('''CREATE TABLE kernel_configs (
    config_id INTEGER PRIMARY KEY,
    block_m INTEGER,
    block_n INTEGER,
    block_k INTEGER,
    group_size_m INTEGER,
    num_stages INTEGER,
    num_warps INTEGER
)''')
configs = [
    (0, 128, 128, 64,  8, 3, 4),
    (1, 128, 256, 64,  8, 3, 8),
    (2, 128, 128, 128, 8, 4, 4),
    (3, 128, 256, 128, 8, 2, 8),
    (4, 128, 128, 64,  8, 2, 8),
    (5, 64,  64,  64,  8, 4, 4),
]
c.executemany('INSERT INTO kernel_configs VALUES (?,?,?,?,?,?,?)', configs)

# Matrix multiplication workloads
c.execute('''CREATE TABLE workloads (
    workload_id INTEGER PRIMARY KEY,
    dim_m INTEGER,
    dim_n INTEGER,
    dim_k INTEGER
)''')
workloads = [
    (0, 4096, 4096, 4096),
    (1, 2048, 4096, 1024),
    (2, 1024, 1024, 8192),
    (3, 768,  2048, 4096),
    (4, 512,  512,  512),
    (5, 256,  8192, 256),
]
c.executemany('INSERT INTO workloads VALUES (?,?,?,?)', workloads)

conn.commit()
conn.close()
print(f"Database created at {db_path}")
