CREATE TABLE nodes (
    name TEXT PRIMARY KEY,
    gpu TEXT NOT NULL,
    compute_cap_major INTEGER NOT NULL,
    compute_cap_minor INTEGER NOT NULL,
    gpu_memory_gb INTEGER NOT NULL,
    cuda_version TEXT NOT NULL,
    cpu_cores INTEGER NOT NULL,
    system_memory_gb INTEGER NOT NULL,
    nvcc_threads INTEGER NOT NULL,
    peak_tflops_fp16 REAL NOT NULL,
    memory_bandwidth_gbps REAL NOT NULL,
    cost_per_hour_usd REAL NOT NULL
);

INSERT INTO nodes VALUES ('ampere-a100', 'NVIDIA A100 80GB SXM', 8, 0, 80, '11.8.0', 64, 256, 4, 312.0, 2039.0, 3.50);
INSERT INTO nodes VALUES ('ampere-a10', 'NVIDIA A10', 8, 6, 24, '12.4.0', 16, 64, 2, 125.0, 600.0, 1.20);
INSERT INTO nodes VALUES ('hopper-h100', 'NVIDIA H100 80GB SXM', 9, 0, 80, '12.8.0', 128, 512, 4, 990.0, 3350.0, 8.50);
INSERT INTO nodes VALUES ('blackwell-b200', 'NVIDIA B200', 10, 0, 192, '12.9.0', 128, 1024, 4, 1800.0, 8000.0, 18.00);
INSERT INTO nodes VALUES ('thor-gh200', 'NVIDIA GH200 Thor', 11, 0, 141, '12.8.0', 72, 480, 4, 990.0, 4900.0, 12.00);
