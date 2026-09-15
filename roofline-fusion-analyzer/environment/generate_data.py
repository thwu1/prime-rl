#!/usr/bin/env python3
"""Generate evaluation data for the benchmark audit task.
Planted anomalies:
  R13, R14 - exceeds roofline (reward hacking)
  R15, R16 - tolerance mismatch (fp32 with fp16-level tolerance)
  R17, R18 - timing instability (high coefficient of variation)
  R19, R20 - cache artifact (bimodal timing distribution)
"""
import json
import os

os.makedirs('/app/eval_data', exist_ok=True)

hardware = {
    "A100": {
        "name": "NVIDIA A100-SXM4-80GB",
        "peak_flops_fp32": 19500000000000,
        "peak_flops_fp16": 312000000000000,
        "memory_bandwidth_bytes_per_sec": 2039000000000,
        "l2_cache_bytes": 41943040
    },
    "V100": {
        "name": "NVIDIA V100-SXM2-32GB",
        "peak_flops_fp32": 15700000000000,
        "peak_flops_fp16": 125000000000000,
        "memory_bandwidth_bytes_per_sec": 900000000000,
        "l2_cache_bytes": 6291456
    }
}

problems = [
    {
        "problem_id": 1,
        "name": "matmul_4096",
        "description": "Dense matrix multiplication C = A @ B, A: 4096x4096, B: 4096x4096",
        "total_flops": 137438953472,
        "total_memory_bytes": 201326592,
        "default_precision": "fp32"
    },
    {
        "problem_id": 2,
        "name": "conv_resnet_block",
        "description": "Conv2d 64->128 channels, 3x3 kernel, stride 1, pad 1, batch 32, 56x56 spatial",
        "total_flops": 14797504512,
        "total_memory_bytes": 77365248,
        "default_precision": "fp32"
    },
    {
        "problem_id": 3,
        "name": "attention_qk_product",
        "description": "Multi-head attention QK^T product, 16 heads, seq_len=512, head_dim=64",
        "total_flops": 536870912,
        "total_memory_bytes": 10485760,
        "default_precision": "fp16"
    },
    {
        "problem_id": 4,
        "name": "gelu_activation",
        "description": "GELU activation on 4M element tensor (batch=1024, features=4096)",
        "total_flops": 33554432,
        "total_memory_bytes": 33554432,
        "default_precision": "fp32"
    },
    {
        "problem_id": 5,
        "name": "transformer_ffn",
        "description": "Transformer FFN: Linear(768,3072) -> GELU -> Linear(3072,768), batch=128",
        "total_flops": 1211105280,
        "total_memory_bytes": 25952256,
        "default_precision": "fp32"
    }
]

results = [
    {
        "result_id": "R01",
        "problem_id": 1,
        "hardware": "A100",
        "kernel_name": "kernel_a",
        "compiled": True,
        "correctness": True,
        "precision": "fp32",
        "tolerance": {"atol": 1e-4, "rtol": 1e-4},
        "ref_timing_trials_us": [14850, 15100, 14920, 15050, 14980, 15020, 14900, 15080, 14960, 15040],
        "kernel_timing_trials_us": [12400, 12550, 12480, 12520, 12450, 12510, 12470, 12530, 12490, 12500],
        "metadata": {}
    },
    {
        "result_id": "R02",
        "problem_id": 1,
        "hardware": "V100",
        "kernel_name": "kernel_a",
        "compiled": True,
        "correctness": True,
        "precision": "fp32",
        "tolerance": {"atol": 1e-4, "rtol": 1e-4},
        "ref_timing_trials_us": [17900, 18100, 17950, 18050, 18000, 17980, 18020, 17960, 18040, 17970],
        "kernel_timing_trials_us": [16300, 16400, 16350, 16380, 16320, 16370, 16340, 16390, 16360, 16350],
        "metadata": {}
    },
    {
        "result_id": "R03",
        "problem_id": 2,
        "hardware": "A100",
        "kernel_name": "kernel_b",
        "compiled": True,
        "correctness": True,
        "precision": "fp32",
        "tolerance": {"atol": 1e-4, "rtol": 1e-4},
        "ref_timing_trials_us": [1980, 2020, 1990, 2010, 2000, 1985, 2015, 1995, 2005, 1992],
        "kernel_timing_trials_us": [1320, 1340, 1330, 1335, 1325, 1338, 1328, 1342, 1332, 1336],
        "metadata": {}
    },
    {
        "result_id": "R04",
        "problem_id": 2,
        "hardware": "V100",
        "kernel_name": "kernel_b",
        "compiled": True,
        "correctness": True,
        "precision": "fp32",
        "tolerance": {"atol": 1e-4, "rtol": 1e-4},
        "ref_timing_trials_us": [2780, 2820, 2790, 2810, 2800, 2785, 2815, 2795, 2805, 2792],
        "kernel_timing_trials_us": [2140, 2160, 2150, 2155, 2145, 2158, 2148, 2162, 2152, 2156],
        "metadata": {}
    },
    {
        "result_id": "R05",
        "problem_id": 3,
        "hardware": "A100",
        "kernel_name": "kernel_c",
        "compiled": True,
        "correctness": True,
        "precision": "fp16",
        "tolerance": {"atol": 1e-2, "rtol": 1e-2},
        "ref_timing_trials_us": [11.8, 12.2, 11.9, 12.1, 12.0, 11.85, 12.15, 11.95, 12.05, 11.92],
        "kernel_timing_trials_us": [6.60, 6.70, 6.65, 6.68, 6.62, 6.69, 6.63, 6.71, 6.66, 6.67],
        "metadata": {}
    },
    {
        "result_id": "R06",
        "problem_id": 3,
        "hardware": "V100",
        "kernel_name": "kernel_c",
        "compiled": True,
        "correctness": True,
        "precision": "fp16",
        "tolerance": {"atol": 1e-2, "rtol": 1e-2},
        "ref_timing_trials_us": [27.8, 28.2, 27.9, 28.1, 28.0, 27.85, 28.15, 27.95, 28.05, 27.92],
        "kernel_timing_trials_us": [19.90, 20.10, 19.95, 20.05, 20.00, 19.92, 20.08, 19.98, 20.02, 19.96],
        "metadata": {}
    },
    {
        "result_id": "R07",
        "problem_id": 4,
        "hardware": "A100",
        "kernel_name": "kernel_d",
        "compiled": True,
        "correctness": True,
        "precision": "fp32",
        "tolerance": {"atol": 1e-4, "rtol": 1e-4},
        "ref_timing_trials_us": [34.8, 35.2, 34.9, 35.1, 35.0, 34.85, 35.15, 34.95, 35.05, 34.92],
        "kernel_timing_trials_us": [49.5, 50.5, 49.8, 50.2, 50.0, 49.6, 50.4, 49.9, 50.1, 49.7],
        "metadata": {}
    },
    {
        "result_id": "R08",
        "problem_id": 4,
        "hardware": "V100",
        "kernel_name": "kernel_d",
        "compiled": True,
        "correctness": True,
        "precision": "fp32",
        "tolerance": {"atol": 1e-4, "rtol": 1e-4},
        "ref_timing_trials_us": [79.5, 80.5, 79.8, 80.2, 80.0, 79.6, 80.4, 79.9, 80.1, 79.7],
        "kernel_timing_trials_us": [99.5, 100.5, 99.8, 100.2, 100.0, 99.6, 100.4, 99.9, 100.1, 99.7],
        "metadata": {}
    },
    {
        "result_id": "R09",
        "problem_id": 5,
        "hardware": "A100",
        "kernel_name": "kernel_e",
        "compiled": True,
        "correctness": True,
        "precision": "fp32",
        "tolerance": {"atol": 1e-4, "rtol": 1e-4},
        "ref_timing_trials_us": [198, 202, 199, 201, 200, 198.5, 201.5, 199.5, 200.5, 199.2],
        "kernel_timing_trials_us": [94.5, 95.5, 94.8, 95.2, 95.0, 94.6, 95.4, 94.9, 95.1, 94.7],
        "metadata": {}
    },
    {
        "result_id": "R10",
        "problem_id": 5,
        "hardware": "V100",
        "kernel_name": "kernel_e",
        "compiled": True,
        "correctness": True,
        "precision": "fp32",
        "tolerance": {"atol": 1e-4, "rtol": 1e-4},
        "ref_timing_trials_us": [278, 282, 279, 281, 280, 278.5, 281.5, 279.5, 280.5, 279.2],
        "kernel_timing_trials_us": [174, 176, 174.5, 175.5, 175, 174.2, 175.8, 174.8, 175.2, 174.6],
        "metadata": {}
    },
    {
        "result_id": "R11",
        "problem_id": 1,
        "hardware": "A100",
        "kernel_name": "kernel_f",
        "compiled": False,
        "correctness": False,
        "precision": "fp32",
        "tolerance": {"atol": 1e-4, "rtol": 1e-4},
        "ref_timing_trials_us": [14850, 15100, 14920, 15050, 14980, 15020, 14900, 15080, 14960, 15040],
        "kernel_timing_trials_us": None,
        "metadata": {"error": "nvcc compilation failed: undefined symbol 'cusolver_kernel'"}
    },
    {
        "result_id": "R12",
        "problem_id": 2,
        "hardware": "A100",
        "kernel_name": "kernel_g",
        "compiled": True,
        "correctness": False,
        "precision": "fp32",
        "tolerance": {"atol": 1e-4, "rtol": 1e-4},
        "ref_timing_trials_us": [1980, 2020, 1990, 2010, 2000, 1985, 2015, 1995, 2005, 1992],
        "kernel_timing_trials_us": [1780, 1820, 1790, 1810, 1800, 1785, 1815, 1795, 1805, 1792],
        "metadata": {"error": "output mismatch: max absolute difference = 0.0523, exceeds tolerance"}
    },
    {
        "result_id": "R13",
        "problem_id": 1,
        "hardware": "A100",
        "kernel_name": "kernel_h",
        "compiled": True,
        "correctness": True,
        "precision": "fp32",
        "tolerance": {"atol": 1e-4, "rtol": 1e-4},
        "ref_timing_trials_us": [14850, 15100, 14920, 15050, 14980, 15020, 14900, 15080, 14960, 15040],
        "kernel_timing_trials_us": [980, 1020, 990, 1010, 1000, 985, 1015, 995, 1005, 992],
        "metadata": {"warning": "excessive speedup detected"}
    },
    {
        "result_id": "R14",
        "problem_id": 3,
        "hardware": "A100",
        "kernel_name": "kernel_i",
        "compiled": True,
        "correctness": True,
        "precision": "fp16",
        "tolerance": {"atol": 1e-2, "rtol": 1e-2},
        "ref_timing_trials_us": [11.8, 12.2, 11.9, 12.1, 12.0, 11.85, 12.15, 11.95, 12.05, 11.92],
        "kernel_timing_trials_us": [0.048, 0.052, 0.049, 0.051, 0.050, 0.0485, 0.0515, 0.0495, 0.0505, 0.0492],
        "metadata": {"warning": "excessive speedup detected"}
    },
    {
        "result_id": "R15",
        "problem_id": 2,
        "hardware": "A100",
        "kernel_name": "kernel_j",
        "compiled": True,
        "correctness": True,
        "precision": "fp32",
        "tolerance": {"atol": 0.01, "rtol": 0.01},
        "ref_timing_trials_us": [1980, 2020, 1990, 2010, 2000, 1985, 2015, 1995, 2005, 1992],
        "kernel_timing_trials_us": [1400, 1420, 1410, 1415, 1405, 1418, 1408, 1422, 1412, 1416],
        "metadata": {}
    },
    {
        "result_id": "R16",
        "problem_id": 5,
        "hardware": "A100",
        "kernel_name": "kernel_k",
        "compiled": True,
        "correctness": True,
        "precision": "fp32",
        "tolerance": {"atol": 0.01, "rtol": 0.01},
        "ref_timing_trials_us": [198, 202, 199, 201, 200, 198.5, 201.5, 199.5, 200.5, 199.2],
        "kernel_timing_trials_us": [108, 112, 109, 111, 110, 108.5, 111.5, 109.5, 110.5, 109.2],
        "metadata": {}
    },
    {
        "result_id": "R17",
        "problem_id": 2,
        "hardware": "A100",
        "kernel_name": "kernel_l",
        "compiled": True,
        "correctness": True,
        "precision": "fp32",
        "tolerance": {"atol": 1e-4, "rtol": 1e-4},
        "ref_timing_trials_us": [1980, 2020, 1990, 2010, 2000, 1985, 2015, 1995, 2005, 1992],
        "kernel_timing_trials_us": [800, 2100, 1300, 3200, 900, 2800, 1100, 2500, 1400, 1900],
        "metadata": {}
    },
    {
        "result_id": "R18",
        "problem_id": 4,
        "hardware": "V100",
        "kernel_name": "kernel_m",
        "compiled": True,
        "correctness": True,
        "precision": "fp32",
        "tolerance": {"atol": 1e-4, "rtol": 1e-4},
        "ref_timing_trials_us": [79.5, 80.5, 79.8, 80.2, 80.0, 79.6, 80.4, 79.9, 80.1, 79.7],
        "kernel_timing_trials_us": [30, 120, 45, 150, 60, 110, 35, 140, 55, 95],
        "metadata": {}
    },
    {
        "result_id": "R19",
        "problem_id": 1,
        "hardware": "V100",
        "kernel_name": "kernel_n",
        "compiled": True,
        "correctness": True,
        "precision": "fp32",
        "tolerance": {"atol": 1e-4, "rtol": 1e-4},
        "ref_timing_trials_us": [17900, 18100, 17950, 18050, 18000, 17980, 18020, 17960, 18040, 17970],
        "kernel_timing_trials_us": [8000, 7500, 7800, 14000, 14200, 14100, 13800, 14300, 14000, 13900],
        "metadata": {}
    },
    {
        "result_id": "R20",
        "problem_id": 5,
        "hardware": "A100",
        "kernel_name": "kernel_o",
        "compiled": True,
        "correctness": True,
        "precision": "fp32",
        "tolerance": {"atol": 1e-4, "rtol": 1e-4},
        "ref_timing_trials_us": [198, 202, 199, 201, 200, 198.5, 201.5, 199.5, 200.5, 199.2],
        "kernel_timing_trials_us": [58, 62, 56, 60, 105, 108, 102, 107, 104, 106],
        "metadata": {}
    }
]

with open('/app/eval_data/hardware.json', 'w') as f:
    json.dump(hardware, f, indent=2)

with open('/app/eval_data/problems.json', 'w') as f:
    json.dump(problems, f, indent=2)

with open('/app/eval_data/results.json', 'w') as f:
    json.dump(results, f, indent=2)

print("Generated eval data: hardware.json, problems.json, results.json")
