CREATE TABLE gpu_specs (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    architecture TEXT NOT NULL,
    peak_tflops REAL NOT NULL,
    bandwidth_gb_s REAL NOT NULL,
    memory_gb REAL NOT NULL
);

INSERT INTO gpu_specs VALUES (1, 'NVIDIA H100 SXM', 'Hopper', 312.0, 2000.0, 80.0);
INSERT INTO gpu_specs VALUES (2, 'NVIDIA H100 PCIe', 'Hopper', 267.6, 2000.0, 80.0);
INSERT INTO gpu_specs VALUES (3, 'NVIDIA A100 SXM', 'Ampere', 156.0, 2039.0, 80.0);
INSERT INTO gpu_specs VALUES (4, 'NVIDIA A100 PCIe', 'Ampere', 156.0, 1555.0, 40.0);
