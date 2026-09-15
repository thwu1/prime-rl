-- GPU Hardware Specifications Database
-- Contains specs for multiple GPU models across several tables.

CREATE TABLE gpu_specs (
    gpu_name TEXT NOT NULL,
    spec_category TEXT NOT NULL,
    spec_name TEXT NOT NULL,
    spec_value REAL NOT NULL,
    unit TEXT,
    notes TEXT,
    PRIMARY KEY (gpu_name, spec_category, spec_name)
);

CREATE TABLE kernel_profiles (
    kernel_type TEXT NOT NULL,
    parameter TEXT NOT NULL,
    value REAL NOT NULL,
    description TEXT,
    PRIMARY KEY (kernel_type, parameter)
);

-- ============================================================
-- GPU-X100 specifications
-- ============================================================

-- SM resources
INSERT INTO gpu_specs VALUES ('GPU-X100', 'sm_resources', 'num_sms', 108, 'count', NULL);
INSERT INTO gpu_specs VALUES ('GPU-X100', 'sm_resources', 'max_warps_per_sm', 64, 'count', NULL);
INSERT INTO gpu_specs VALUES ('GPU-X100', 'sm_resources', 'max_blocks_per_sm', 32, 'count', NULL);
INSERT INTO gpu_specs VALUES ('GPU-X100', 'sm_resources', 'max_threads_per_sm', 2048, 'count', NULL);
INSERT INTO gpu_specs VALUES ('GPU-X100', 'sm_resources', 'warp_size', 32, 'threads', NULL);

-- Register file
INSERT INTO gpu_specs VALUES ('GPU-X100', 'registers', 'register_file_size', 65536, 'registers', 'total 32-bit registers per SM');
INSERT INTO gpu_specs VALUES ('GPU-X100', 'registers', 'max_registers_per_thread', 255, 'registers', NULL);
INSERT INTO gpu_specs VALUES ('GPU-X100', 'registers', 'allocation_granularity', 8, 'registers', 'hardware allocates in multiples of this value');

-- Shared memory
INSERT INTO gpu_specs VALUES ('GPU-X100', 'shared_memory', 'shared_memory_per_sm', 167936, 'bytes', NULL);
INSERT INTO gpu_specs VALUES ('GPU-X100', 'shared_memory', 'max_shared_memory_per_block', 167936, 'bytes', NULL);

-- Memory hierarchy
INSERT INTO gpu_specs VALUES ('GPU-X100', 'memory', 'l2_cache_size', 41943040, 'bytes', NULL);
INSERT INTO gpu_specs VALUES ('GPU-X100', 'memory', 'hbm_bandwidth', 2039.0, 'GB/s', NULL);

-- Compute capabilities
INSERT INTO gpu_specs VALUES ('GPU-X100', 'compute', 'fp16_tflops', 312.0, 'TFLOPS', NULL);
INSERT INTO gpu_specs VALUES ('GPU-X100', 'compute', 'fp16_element_size', 2, 'bytes', NULL);

-- ============================================================
-- GPU-V200 specifications (distractor)
-- ============================================================

INSERT INTO gpu_specs VALUES ('GPU-V200', 'sm_resources', 'num_sms', 80, 'count', NULL);
INSERT INTO gpu_specs VALUES ('GPU-V200', 'sm_resources', 'max_warps_per_sm', 64, 'count', NULL);
INSERT INTO gpu_specs VALUES ('GPU-V200', 'sm_resources', 'max_blocks_per_sm', 32, 'count', NULL);
INSERT INTO gpu_specs VALUES ('GPU-V200', 'sm_resources', 'max_threads_per_sm', 2048, 'count', NULL);
INSERT INTO gpu_specs VALUES ('GPU-V200', 'sm_resources', 'warp_size', 32, 'threads', NULL);
INSERT INTO gpu_specs VALUES ('GPU-V200', 'registers', 'register_file_size', 65536, 'registers', NULL);
INSERT INTO gpu_specs VALUES ('GPU-V200', 'registers', 'max_registers_per_thread', 255, 'registers', NULL);
INSERT INTO gpu_specs VALUES ('GPU-V200', 'registers', 'allocation_granularity', 8, 'registers', NULL);
INSERT INTO gpu_specs VALUES ('GPU-V200', 'shared_memory', 'shared_memory_per_sm', 98304, 'bytes', NULL);
INSERT INTO gpu_specs VALUES ('GPU-V200', 'shared_memory', 'max_shared_memory_per_block', 98304, 'bytes', NULL);
INSERT INTO gpu_specs VALUES ('GPU-V200', 'memory', 'l2_cache_size', 6291456, 'bytes', NULL);
INSERT INTO gpu_specs VALUES ('GPU-V200', 'memory', 'hbm_bandwidth', 900.0, 'GB/s', NULL);
INSERT INTO gpu_specs VALUES ('GPU-V200', 'compute', 'fp16_tflops', 125.0, 'TFLOPS', NULL);
INSERT INTO gpu_specs VALUES ('GPU-V200', 'compute', 'fp16_element_size', 2, 'bytes', NULL);

-- ============================================================
-- GPU-H300 specifications (distractor)
-- ============================================================

INSERT INTO gpu_specs VALUES ('GPU-H300', 'sm_resources', 'num_sms', 132, 'count', NULL);
INSERT INTO gpu_specs VALUES ('GPU-H300', 'sm_resources', 'max_warps_per_sm', 64, 'count', NULL);
INSERT INTO gpu_specs VALUES ('GPU-H300', 'sm_resources', 'max_blocks_per_sm', 32, 'count', NULL);
INSERT INTO gpu_specs VALUES ('GPU-H300', 'sm_resources', 'max_threads_per_sm', 2048, 'count', NULL);
INSERT INTO gpu_specs VALUES ('GPU-H300', 'sm_resources', 'warp_size', 32, 'threads', NULL);
INSERT INTO gpu_specs VALUES ('GPU-H300', 'registers', 'register_file_size', 65536, 'registers', NULL);
INSERT INTO gpu_specs VALUES ('GPU-H300', 'registers', 'max_registers_per_thread', 255, 'registers', NULL);
INSERT INTO gpu_specs VALUES ('GPU-H300', 'registers', 'allocation_granularity', 8, 'registers', NULL);
INSERT INTO gpu_specs VALUES ('GPU-H300', 'shared_memory', 'shared_memory_per_sm', 233472, 'bytes', NULL);
INSERT INTO gpu_specs VALUES ('GPU-H300', 'shared_memory', 'max_shared_memory_per_block', 233472, 'bytes', NULL);
INSERT INTO gpu_specs VALUES ('GPU-H300', 'memory', 'l2_cache_size', 52428800, 'bytes', NULL);
INSERT INTO gpu_specs VALUES ('GPU-H300', 'memory', 'hbm_bandwidth', 3350.0, 'GB/s', NULL);
INSERT INTO gpu_specs VALUES ('GPU-H300', 'compute', 'fp16_tflops', 990.0, 'TFLOPS', NULL);
INSERT INTO gpu_specs VALUES ('GPU-H300', 'compute', 'fp16_element_size', 2, 'bytes', NULL);

-- ============================================================
-- Kernel resource profiles
-- ============================================================

INSERT INTO kernel_profiles VALUES ('tiled_matmul', 'register_overhead_per_thread', 40, 'addressing, loop induction, masks, control flow');
INSERT INTO kernel_profiles VALUES ('tiled_matmul', 'accumulator_precision_bits', 32, 'fp32 accumulator for numerical stability');
INSERT INTO kernel_profiles VALUES ('fused_softmax', 'register_overhead_per_thread', 24, 'pointer arithmetic and online reduction');
INSERT INTO kernel_profiles VALUES ('fused_softmax', 'accumulator_precision_bits', 32, 'fp32 for numerical stability');
INSERT INTO kernel_profiles VALUES ('layer_norm', 'register_overhead_per_thread', 32, 'mean/variance tracking and normalization');
INSERT INTO kernel_profiles VALUES ('layer_norm', 'accumulator_precision_bits', 32, 'fp32 accumulation');
INSERT INTO kernel_profiles VALUES ('flash_attention', 'register_overhead_per_thread', 48, 'QKV pointers, scaling, causal masking');
INSERT INTO kernel_profiles VALUES ('flash_attention', 'accumulator_precision_bits', 32, 'fp32 accumulation');
