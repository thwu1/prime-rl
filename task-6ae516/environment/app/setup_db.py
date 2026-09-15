#!/usr/bin/env python3
"""Creates the profiling SQLite database for the GPU kernel fleet audit task."""
import sqlite3

conn = sqlite3.connect('/app/profiling.db')
cur = conn.cursor()

cur.execute('''CREATE TABLE kernels (
    kernel_name TEXT PRIMARY KEY,
    block_dim_x INTEGER NOT NULL,
    block_dim_y INTEGER NOT NULL,
    block_dim_z INTEGER NOT NULL,
    registers_per_thread INTEGER NOT NULL,
    static_smem_bytes INTEGER NOT NULL,
    dynamic_smem_bytes INTEGER NOT NULL
)''')

cur.execute('''CREATE TABLE global_memory_accesses (
    kernel_name TEXT NOT NULL,
    access_name TEXT NOT NULL,
    element_size_bytes INTEGER NOT NULL,
    stride_elements INTEGER NOT NULL,
    PRIMARY KEY (kernel_name, access_name),
    FOREIGN KEY (kernel_name) REFERENCES kernels(kernel_name)
)''')

cur.execute('''CREATE TABLE shared_memory_accesses (
    kernel_name TEXT NOT NULL,
    access_name TEXT NOT NULL,
    element_size_bytes INTEGER NOT NULL,
    index_coefficient INTEGER NOT NULL,
    index_constant INTEGER NOT NULL,
    PRIMARY KEY (kernel_name, access_name),
    FOREIGN KEY (kernel_name) REFERENCES kernels(kernel_name)
)''')

cur.execute('''CREATE TABLE pipeline_edges (
    source_kernel TEXT NOT NULL,
    dest_kernel TEXT NOT NULL,
    intermediate_data_mb REAL NOT NULL,
    PRIMARY KEY (source_kernel, dest_kernel),
    FOREIGN KEY (source_kernel) REFERENCES kernels(kernel_name),
    FOREIGN KEY (dest_kernel) REFERENCES kernels(kernel_name)
)''')

kernels = [
    ('gemm_tile', 256, 1, 1, 40, 32768, 0),
    ('reduce_atomic', 512, 1, 1, 48, 0, 0),
    ('transpose_opt', 32, 8, 1, 24, 4096, 0),
    ('conv_smem', 128, 1, 1, 96, 49152, 0),
    ('fft_radix', 256, 1, 1, 64, 8192, 0),
]
cur.executemany('INSERT INTO kernels VALUES (?,?,?,?,?,?,?)', kernels)

global_mem = [
    ('gemm_tile', 'tile_load_A', 4, 1),
    ('gemm_tile', 'tile_load_B', 4, 128),
    ('gemm_tile', 'result_store', 4, 1),
    ('reduce_atomic', 'input_read', 4, 1),
    ('transpose_opt', 'coalesced_read', 4, 1),
    ('transpose_opt', 'strided_write', 4, 1024),
    ('conv_smem', 'input_load', 4, 1),
    ('conv_smem', 'filter_load', 4, 1),
    ('conv_smem', 'output_store', 4, 1),
    ('fft_radix', 'butterfly_read', 8, 1),
    ('fft_radix', 'butterfly_write', 8, 1),
    ('fft_radix', 'twiddle_load', 8, 16),
]
cur.executemany('INSERT INTO global_memory_accesses VALUES (?,?,?,?)', global_mem)

shared_mem = [
    ('gemm_tile', 'smem_row', 4, 1, 0),
    ('gemm_tile', 'smem_col', 4, 32, 0),
    ('transpose_opt', 'unpadded_col', 4, 32, 0),
    ('transpose_opt', 'padded_col', 4, 33, 0),
    ('transpose_opt', 'diagonal', 4, 33, 1),
    ('conv_smem', 'smem_linear', 4, 1, 0),
    ('conv_smem', 'smem_stride4', 4, 4, 0),
    ('fft_radix', 'butterfly_smem', 4, 2, 0),
    ('fft_radix', 'butterfly_smem_rev', 4, 16, 0),
]
cur.executemany('INSERT INTO shared_memory_accesses VALUES (?,?,?,?,?)', shared_mem)

edges = [
    ('gemm_tile', 'transpose_opt', 256.0),
    ('transpose_opt', 'fft_radix', 128.0),
    ('conv_smem', 'fft_radix', 64.0),
    ('fft_radix', 'reduce_atomic', 32.0),
    ('conv_smem', 'reduce_atomic', 16.0),
]
cur.executemany('INSERT INTO pipeline_edges VALUES (?,?,?)', edges)

conn.commit()
conn.close()
