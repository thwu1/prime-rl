#!/usr/bin/env python3
"""Generate multi-format reference data for tcgen05 layout task.

Creates:
  /app/vectors.db           — SQLite database with address mapping vectors
  /app/descriptors/*.bin    — Raw binary descriptor files + manifest
  /app/hw_config_dump.json  — Nested hardware config with TMA test cases
"""
import sqlite3
import struct
import json
import os

# ======================================================================
# 1. SQLite database — address mapping and inverse mapping vectors
# ======================================================================

db = sqlite3.connect("/app/vectors.db")
db.execute("PRAGMA journal_mode=WAL")
c = db.cursor()

c.execute("""CREATE TABLE swizzle_modes (
    mode_id   INTEGER PRIMARY KEY,
    mode_name TEXT UNIQUE NOT NULL,
    chunk_width_bytes INTEGER NOT NULL,
    smem_descriptor_code INTEGER,
    notes TEXT
)""")

c.executemany("INSERT INTO swizzle_modes VALUES (?, ?, ?, ?, ?)", [
    (0, "NONE", 16,  0,    "No rearrangement; each strip is a single 16-byte column"),
    (1, "32B",  32,  None, "2 units per row; supported in address mapping but not smem descriptor"),
    (2, "64B",  64,  None, "4 units per row; supported in address mapping but not smem descriptor"),
    (3, "128B", 128, 2,    "8 units per row; full core-matrix width"),
])

c.execute("""CREATE TABLE address_vectors (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    row_idx     INTEGER NOT NULL,
    col_bytes   INTEGER NOT NULL,
    tile_height INTEGER NOT NULL,
    mode_id     INTEGER NOT NULL REFERENCES swizzle_modes(mode_id),
    physical_offset INTEGER NOT NULL
)""")

c.execute("""CREATE TABLE inverse_vectors (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    physical_offset INTEGER NOT NULL,
    tile_height     INTEGER NOT NULL,
    tile_width_bytes INTEGER NOT NULL,
    mode_id         INTEGER NOT NULL REFERENCES swizzle_modes(mode_id),
    result_row      INTEGER NOT NULL,
    result_col_bytes INTEGER NOT NULL
)""")

c.execute("""CREATE TABLE descriptor_field_info (
    field_name  TEXT PRIMARY KEY,
    bit_start   INTEGER NOT NULL,
    bit_width   INTEGER NOT NULL,
    description TEXT
)""")

# Descriptor bit-field hints (partial — enough to orient but not solve)
c.executemany("INSERT INTO descriptor_field_info VALUES (?, ?, ?, ?)", [
    ("ADDR",    0,  14, "Base address >> 4"),
    ("LBO",     16, 14, "Leading byte offset >> 4; zero for swizzled modes"),
    ("SBO",     32, 14, "Stride byte offset >> 4"),
    ("FLAG",    46, 1,  "Must be set to 1"),
    ("SWIZZLE", 61, 3,  "Swizzle mode code"),
])

# Address mapping reference vectors (mode_id references swizzle_modes)
address_data = [
    # (row, col_bytes, tile_height, mode_id, physical_offset)
    # NONE mode (mode_id=0)
    (0,  0,   128, 0, 0),
    (1,  0,   128, 0, 16),
    (7,  0,   128, 0, 112),
    (8,  0,   128, 0, 128),
    (0,  16,  128, 0, 2048),
    (0,  5,   128, 0, 5),
    (3,  21,  128, 0, 2101),
    (0,  32,  16,  0, 512),
    # 128B mode (mode_id=3)
    (0,  0,   128, 3, 0),
    (1,  0,   128, 3, 144),
    (0,  16,  128, 3, 16),
    (1,  16,  128, 3, 128),
    (7,  0,   128, 3, 1008),
    (8,  0,   128, 3, 1024),
    # 32B mode (mode_id=1)
    (0,  0,   128, 1, 0),
    (1,  0,   128, 1, 48),
    (1,  16,  128, 1, 32),
    (2,  0,   128, 1, 64),
    (3,  16,  128, 1, 96),
    (2,  16,  128, 1, 80),
    # 64B mode (mode_id=2)
    (3,  0,   128, 2, 240),
    (4,  0,   128, 2, 256),
    (2,  32,  128, 2, 128),
    (1,  48,  128, 2, 96),
]
c.executemany(
    "INSERT INTO address_vectors (row_idx, col_bytes, tile_height, mode_id, physical_offset) "
    "VALUES (?, ?, ?, ?, ?)", address_data)

inverse_data = [
    # (physical_offset, tile_height, tile_width_bytes, mode_id, result_row, result_col_bytes)
    (0,   128, 128, 0, 0, 0),
    (16,  128, 128, 0, 1, 0),
    (144, 128, 128, 3, 1, 0),
    (128, 128, 128, 3, 1, 16),
    (48,  64,  32,  1, 1, 0),
    (240, 32,  64,  2, 3, 0),
]
c.executemany(
    "INSERT INTO inverse_vectors (physical_offset, tile_height, tile_width_bytes, mode_id, result_row, result_col_bytes) "
    "VALUES (?, ?, ?, ?, ?, ?)", inverse_data)

# Create a view for convenience
c.execute("""CREATE VIEW address_vectors_named AS
    SELECT a.id, a.row_idx, a.col_bytes, a.tile_height,
           s.mode_name AS swizzle_mode, s.chunk_width_bytes,
           a.physical_offset
    FROM address_vectors a
    JOIN swizzle_modes s ON a.mode_id = s.mode_id
""")

c.execute("""CREATE VIEW inverse_vectors_named AS
    SELECT v.id, v.physical_offset, v.tile_height, v.tile_width_bytes,
           s.mode_name AS swizzle_mode,
           v.result_row, v.result_col_bytes
    FROM inverse_vectors v
    JOIN swizzle_modes s ON v.mode_id = s.mode_id
""")

db.commit()
db.close()

# ======================================================================
# 2. Binary descriptor files — raw packed bit-fields
# ======================================================================

os.makedirs("/app/descriptors", exist_ok=True)

smem_descriptors = [
    ("smem_none_h128_b0000.bin", 0,    128, "NONE", 70403112304640),
    ("smem_none_h064_b0256.bin", 256,  64,  "NONE", 70403108110352),
    ("smem_none_h128_b0048.bin", 48,   128, "NONE", 70403112304643),
    ("smem_128b_h128_b0000.bin", 0,    128, "128B", 4611756662049472512),
    ("smem_128b_h128_b1024.bin", 1024, 128, "128B", 4611756662049472576),
]

for fname, base, h, mode, value in smem_descriptors:
    with open("/app/descriptors/" + fname, "wb") as f:
        f.write(struct.pack("<Q", value))

instr_descriptors = [
    ("instr_fp32_bf16_bf16_128x064.bin", "FP32", "BF16", "BF16", 128, 64,  135267472),
    ("instr_fp16_fp16_fp16_064x128.bin", "FP16", "FP16", "FP16", 64,  128, 69206016),
    ("instr_s32_s8_u8_128x128.bin",      "S32",  "S8",   "U8",  128, 128, 136321696),
]

for fname, acc, a, b, m, n, value in instr_descriptors:
    with open("/app/descriptors/" + fname, "wb") as f:
        f.write(struct.pack("<I", value))

# Manifest — maps filenames to their input parameters
with open("/app/descriptors/manifest.csv", "w") as f:
    f.write("filename,descriptor_type,param_1,param_2,param_3,param_4,param_5\n")
    for fname, base, h, mode, _ in smem_descriptors:
        f.write("%s,smem_64bit,base_addr=%d,tile_height=%d,swizzle=%s,,\n" % (fname, base, h, mode))
    for fname, acc, a, b, m, n, _ in instr_descriptors:
        f.write("%s,instr_32bit,acc_dtype=%s,a_dtype=%s,b_dtype=%s,mma_m=%d,mma_n=%d\n" % (fname, acc, a, b, m, n))

# ======================================================================
# 3. Deeply nested JSON — hardware config dump with TMA test cases
# ======================================================================

hw_config = {
    "device_report": {
        "report_version": "3.2.1",
        "generated_at": "2025-03-15T12:00:00Z",
        "device_uuid": "GPU-a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "driver_version": "570.86.15",
        "cuda_toolkit_version": "13.0.1",
        "architecture": {
            "codename": "Blackwell",
            "sm_version": "sm_100",
            "compute_capability": [10, 0],
            "multiprocessors": 132,
            "cuda_cores_per_sm": 128,
            "warp_size": 32,
            "max_threads_per_block": 1024,
            "max_warps_per_sm": 64,
            "register_file_size_per_sm_kb": 256
        },
        "memory_subsystem": {
            "global_memory_gb": 80,
            "memory_bus_width_bits": 8192,
            "hbm_generation": "HBM3E",
            "peak_bandwidth_tb_per_s": 8.0,
            "l2_cache_mb": 64,
            "shared_memory": {
                "per_sm_kb": 228,
                "configurable_sizes_kb": [0, 8, 16, 32, 64, 100, 132, 164, 228],
                "bank_count": 32,
                "bank_width_bytes": 4,
                "latency_cycles": 20,
                "max_allocation_bytes": 233472
            }
        },
        "execution_units": [
            {
                "unit_family": "tcgen05",
                "generation": "5th_gen_tensor_cores",
                "pipelines_per_sm": 4,
                "peak_tflops_fp16": 2250,
                "capabilities": {
                    "mma_operations": {
                        "core_matrix_shape": {"rows": 8, "cols_bytes": 16},
                        "supported_accumulator_types": [
                            {"dtype": "FP16", "bits": 16, "description": "IEEE half precision"},
                            {"dtype": "FP32", "bits": 32, "description": "IEEE single precision"},
                            {"dtype": "S32",  "bits": 32, "description": "Signed 32-bit integer"}
                        ],
                        "supported_operand_types": [
                            {"dtype": "FP16",    "bits": 16, "elements_per_32b": 2},
                            {"dtype": "BF16",    "bits": 16, "elements_per_32b": 2},
                            {"dtype": "TF32",    "bits": 19, "elements_per_32b": 1},
                            {"dtype": "FP8_E4M3","bits": 8,  "elements_per_32b": 4},
                            {"dtype": "FP8_E5M2","bits": 8,  "elements_per_32b": 4},
                            {"dtype": "S8",      "bits": 8,  "elements_per_32b": 4},
                            {"dtype": "U8",      "bits": 8,  "elements_per_32b": 4}
                        ],
                        "dimension_constraints": {
                            "M_divisor": 16,
                            "N_divisor": 8,
                            "max_M": 256,
                            "max_N": 256,
                            "K_determined_by_dtypes": True
                        }
                    },
                    "tma_engine": {
                        "version": "2.0",
                        "max_tensor_rank": 5,
                        "supported_element_sizes_bytes": [1, 2, 4],
                        "fill_modes": ["NO_FILL", "ZERO_FILL"],
                        "oob_fill_value": 0,
                        "interleave_modes": ["NONE", "16B", "32B"],
                        "swizzle_modes_supported": ["NONE", "32B", "64B", "128B"],
                        "validation_suite": {
                            "description": "Verified TMA 3D tensor-map parameter test cases for K-major global matrix to tcgen05 shared memory layout",
                            "tensor_rank_used": 3,
                            "stride_convention": "globalStrides omits innermost (implicit 1-element stride); 2 strides for rank-3",
                            "cases": {
                                "tma_val_001": {
                                    "label": "BF16 large matmul, NONE swizzle, 4096x4096",
                                    "inputs": {
                                        "M": 4096, "K": 4096,
                                        "block_m": 128, "block_k": 64,
                                        "element_bytes": 2,
                                        "swizzle_mode": "NONE"
                                    },
                                    "expected": {
                                        "globalDim": [8, 4096, 512],
                                        "globalStrides": [8192, 16],
                                        "boxDim": [8, 128, 8]
                                    }
                                },
                                "tma_val_002": {
                                    "label": "BF16 large matmul, 128B swizzle, 4096x4096",
                                    "inputs": {
                                        "M": 4096, "K": 4096,
                                        "block_m": 128, "block_k": 64,
                                        "element_bytes": 2,
                                        "swizzle_mode": "128B"
                                    },
                                    "expected": {
                                        "globalDim": [64, 4096, 64],
                                        "globalStrides": [8192, 128],
                                        "boxDim": [64, 128, 1]
                                    }
                                },
                                "tma_val_003": {
                                    "label": "FP32 medium matmul, NONE swizzle, 2048x1024",
                                    "inputs": {
                                        "M": 2048, "K": 1024,
                                        "block_m": 64, "block_k": 32,
                                        "element_bytes": 4,
                                        "swizzle_mode": "NONE"
                                    },
                                    "expected": {
                                        "globalDim": [4, 2048, 256],
                                        "globalStrides": [4096, 16],
                                        "boxDim": [4, 64, 8]
                                    }
                                }
                            }
                        }
                    }
                }
            },
            {
                "unit_family": "ldmatrix",
                "generation": "legacy_warp_level",
                "pipelines_per_sm": 4,
                "capabilities": {
                    "description": "Legacy warp-level matrix load path (sm_70+). Loads 8x8 matrix fragments from shared memory into register file. Not used by tcgen05.",
                    "supported_shapes": ["m8n8", "m16n16"],
                    "transpose_supported": True
                }
            },
            {
                "unit_family": "dp4a",
                "generation": "integer_dot_product",
                "pipelines_per_sm": 64,
                "capabilities": {
                    "description": "4-element 8-bit integer dot product accumulated into 32-bit. Legacy integer path.",
                    "throughput_per_clock": 256,
                    "input_types": ["S8", "U8"]
                }
            }
        ],
        "profiling_metadata": {
            "ncu_metrics": {
                "bank_conflicts": "smsp__sass_data_bytes_mem_shared_op_atom.sum",
                "tensor_utilization": "sm__pipe_tensor_op_hmma_cycles_active.avg.pct_of_peak_sustained_elapsed",
                "shared_memory_throughput": "l1tex__data_pipe_lsu_wavefronts_mem_shared.avg.pct_of_peak_sustained_elapsed",
                "occupancy": "sm__warps_active.avg.pct_of_peak_sustained_active"
            },
            "compute_sanitizer_checks": [
                "memcheck", "racecheck", "synccheck", "initcheck"
            ]
        }
    }
}

with open("/app/hw_config_dump.json", "w") as f:
    json.dump(hw_config, f, indent=2)

print("Reference data generated: vectors.db, descriptors/, hw_config_dump.json")
