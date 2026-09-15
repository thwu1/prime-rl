#!/usr/bin/env python3
"""Generate benchmark data for the GPU kernel benchmark reconciliation task."""
import json
import csv
import sqlite3
import os


def create_directories():
    for d in ['/app', '/app/legacy', '/app/hardware', '/app/catalog', '/app/baselines']:
        os.makedirs(d, exist_ok=True)


def create_sqlite_db():
    conn = sqlite3.connect('/app/benchmarks.db')
    conn.execute('''CREATE TABLE eval_runs (
        run_id INTEGER PRIMARY KEY,
        model_name TEXT NOT NULL,
        hardware TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        notes TEXT
    )''')
    conn.execute('''CREATE TABLE samples (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER REFERENCES eval_runs(run_id),
        problem_id INTEGER NOT NULL,
        sample_id INTEGER NOT NULL,
        compiled INTEGER NOT NULL,
        correct INTEGER NOT NULL,
        runtime_us REAL
    )''')
    conn.execute('''CREATE INDEX idx_samples_problem ON samples(problem_id, sample_id)''')

    # Run 1: 2024-11-15 — primary evaluation, covers problems 1-10
    conn.execute(
        "INSERT INTO eval_runs VALUES (1, 'deepseek-r1', 'A100-SXM4-80GB', '2024-11-15T10:00:00Z', 'initial evaluation')"
    )
    # Run 2: 2024-12-03 — re-evaluation of problems 1-3 only
    conn.execute(
        "INSERT INTO eval_runs VALUES (2, 'deepseek-r1', 'A100-SXM4-80GB', '2024-12-03T14:30:00Z', 're-evaluation of problems 1-3')"
    )

    # Run 1 data (problems 1-10, 5 samples each)
    run1 = {
        1: [
            (0, 1, 1, 12.0),
            (1, 1, 1, 13.5),
            (2, 1, 1, None),     # NULL runtime — timing failed
            (3, 1, 0, 8.0),
            (4, 1, 1, 14.0),
        ],
        2: [
            (0, 1, 1, 10.0),
            (1, 1, 1, 9.5),
            (2, 1, 1, 10.5),
            (3, 1, 1, 11.0),
            (4, 1, 1, 9.0),
        ],
        3: [
            (0, 1, 1, 130.0),
            (1, 1, 0, 125.0),
            (2, 1, 1, 135.0),
            (3, 0, 0, None),
            (4, 1, 1, 128.0),
        ],
        4: [
            (0, 1, 1, 60.0),
            (1, 1, 1, 55.0),
            (2, 1, 1, 65.0),
            (3, 1, 1, 58.0),
            (4, 1, 1, 62.0),
        ],
        5: [
            (0, 1, 0, 45.0),
            (1, 1, 0, 42.0),
            (2, 0, 0, None),
            (3, 0, 0, None),
            (4, 1, 0, 48.0),
        ],
        6: [
            (0, 1, 1, 350.0),
            (1, 1, 1, 360.0),
            (2, 1, 1, 345.0),
            (3, 1, 1, -5.0),    # Negative runtime — data corruption
            (4, 1, 1, 340.0),
        ],
        7: [
            (0, 1, 1, 5.0),
            (1, 1, 1, 4.5),
            (2, 1, 1, 6.0),
            (3, 1, 1, 5.5),
            (4, 1, 1, 4.0),
        ],
        8: [
            (0, 1, 1, 30.0),
            (1, 1, 1, None),    # NULL runtime — timing failed
            (2, 1, 0, 28.0),
            (3, 1, 1, 31.0),
            (4, 1, 1, 33.0),
        ],
        9: [
            (0, 1, 1, 2.0),
            (1, 1, 1, 7.0),
            (2, 1, 1, 8.0),
            (3, 1, 1, 2.5),
            (4, 1, 1, 7.5),
        ],
        10: [
            (0, 1, 1, 200.0),
            (1, 1, 1, 210.0),
            (2, 1, 1, 195.0),
            (3, 1, 0, 180.0),
            (4, 1, 1, 205.0),
        ],
    }

    # Run 2 data (re-eval of problems 1-3, creates duplicates)
    run2 = {
        1: [
            (0, 1, 1, 12.5),
            (1, 1, 1, 13.0),
        ],
        2: [
            (0, 1, 1, 10.2),
        ],
        3: [
            (0, 1, 1, 131.0),
        ],
    }

    sid = 1
    for pid, samples in run1.items():
        for s in samples:
            conn.execute(
                "INSERT INTO samples (id, run_id, problem_id, sample_id, compiled, correct, runtime_us) VALUES (?, 1, ?, ?, ?, ?, ?)",
                (sid, pid, s[0], s[1], s[2], s[3])
            )
            sid += 1

    for pid, samples in run2.items():
        for s in samples:
            conn.execute(
                "INSERT INTO samples (id, run_id, problem_id, sample_id, compiled, correct, runtime_us) VALUES (?, 2, ?, ?, ?, ?, ?)",
                (sid, pid, s[0], s[1], s[2], s[3])
            )
            sid += 1

    conn.commit()
    conn.close()


def create_legacy_logs():
    # Legacy format uses different field names and millisecond units
    legacy_data_a = {
        8: [
            (0, True, True, 0.035),
            (1, True, False, 0.038),
            (2, True, True, 0.029),
            (3, True, True, 0.033),
            (4, True, True, 0.036),
        ],
        9: [
            (0, True, True, 0.003),
            (1, True, True, 0.008),
            (2, True, True, 0.009),
            (3, True, True, 0.003),
            (4, True, True, 0.008),
        ],
        10: [
            (0, True, True, 0.210),
            (1, True, True, 0.220),
            (2, True, False, 0.200),
            (3, True, False, 0.190),
            (4, True, True, 0.215),
        ],
        11: [
            (0, False, False, -1.0),
            (1, False, False, -1.0),
            (2, True, False, 0.300),
            (3, False, False, -1.0),
            (4, True, True, 0.280),
        ],
        12: [
            (0, True, True, 0.050),
            (1, True, True, 0.055),
            (2, True, False, 0.048),
            (3, True, True, 0.052),
            (4, True, True, 0.060),
        ],
    }

    legacy_data_b = {
        13: [
            (0, True, True, 0.020),
            (1, True, True, 0.022),
            (2, True, False, 0.018),
            (3, True, True, 0.021),
            (4, False, False, -1.0),
        ],
        14: [
            (0, True, True, 0.010),
            (1, True, True, 0.009),
            (2, True, True, 0.011),
            (3, True, False, 0.008),
            (4, True, True, 0.010),
        ],
        15: [
            (0, True, False, 0.008),
            (1, True, False, 0.009),
            (2, False, False, -1.0),
            (3, True, False, 0.010),
            (4, True, False, 0.007),
        ],
    }

    log_a = {
        "run_metadata": {
            "model": "deepseek-r1",
            "hardware": "A100-SXM4-80GB",
            "timestamp": "2024-10-20T08:00:00Z",
            "timing_unit": "milliseconds"
        },
        "results": {}
    }
    for pid, samples in legacy_data_a.items():
        log_a["results"][str(pid)] = [
            {"sample_id": s[0], "built": s[1], "passed": s[2], "exec_time_ms": s[3]}
            for s in samples
        ]

    log_b = {
        "run_metadata": {
            "model": "deepseek-r1",
            "hardware": "A100-SXM4-80GB",
            "timestamp": "2024-10-25T12:00:00Z",
            "timing_unit": "milliseconds"
        },
        "results": {}
    }
    for pid, samples in legacy_data_b.items():
        log_b["results"][str(pid)] = [
            {"sample_id": s[0], "built": s[1], "passed": s[2], "exec_time_ms": s[3]}
            for s in samples
        ]

    with open('/app/legacy/eval_run_20241020.json', 'w') as f:
        json.dump(log_a, f, indent=2)
    with open('/app/legacy/eval_run_20241025.json', 'w') as f:
        json.dump(log_b, f, indent=2)


def create_hardware_toml():
    content = """# GPU Hardware Specification
# NVIDIA A100 SXM4 80GB — Ampere Architecture

[gpu]
name = "NVIDIA A100-SXM4-80GB"
architecture = "Ampere"
sm_count = 108

[gpu.compute]
peak_fp32_tflops = 19.5
peak_fp16_tflops = 312.0
peak_tf32_tflops = 156.0
tensor_core_fp16_tflops = 624.0

[gpu.memory]
bandwidth_gb_s = 2039.0
capacity_gb = 80
type = "HBM2e"

[gpu.cache]
l2_size_mb = 40
shared_memory_kb_per_sm = 164

[gpu.clocks]
base_mhz = 1095
boost_mhz = 1410
memory_mhz = 1593
"""
    with open('/app/hardware/system_info.toml', 'w') as f:
        f.write(content)


def create_catalog_csv():
    problems = [
        (1, "vector_add", "elementwise", 1000000, 12000000),
        (2, "vector_multiply", "elementwise", 1000000, 12000000),
        (3, "matmul_small", "matmul", 2000000000, 12000000),
        (4, "softmax", "activation", 100000000, 80000000),         # WRONG flops (should be 50000000)
        (5, "layernorm", "normalization", 30000000, 40000000),
        (6, "conv2d_3x3", "convolution", 5000000000, 200000000),
        (7, "batchnorm", "normalization", 20000000, 60000000),
        (8, "reduction_sum", "reduction", 500000000, 40000000),     # WRONG flops (should be 10000000)
        (9, "gelu_activation", "activation", 5000000, 8000000),
        (10, "conv2d_relu_bias", "fusion", 3000000000, 100000000),
        (11, "matmul_scale_residual", "fusion", 400000000, 150000000),  # WRONG flops (should be 4000000000)
        (12, "attention_fused", "attention", 8000000000, 500000000),
        (13, "embedding_lookup", "memory_op", 2000000, 32000000),
        (14, "residual_add", "elementwise", 1000000, 16000000),
        (15, "dropout_fwd", "regularization", 1500000, 16000000),
    ]

    with open('/app/catalog/problems.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['problem_id', 'name', 'category', 'flops', 'memory_bytes'])
        for p in problems:
            writer.writerow(p)


def create_errata():
    errata = {
        "description": "Known corrections to problem catalog FLOPs counts identified during post-hoc analysis",
        "date": "2024-12-10",
        "corrections": [
            {
                "problem_id": 4,
                "field": "flops",
                "incorrect_value": 100000000,
                "corrected_value": 50000000,
                "reason": "Double-counted due to fused multiply-add being counted as two separate operations"
            },
            {
                "problem_id": 8,
                "field": "flops",
                "incorrect_value": 500000000,
                "corrected_value": 10000000,
                "reason": "Incorrectly included reduction tree intermediate operations in FLOPs count"
            },
            {
                "problem_id": 11,
                "field": "flops",
                "incorrect_value": 400000000,
                "corrected_value": 4000000000,
                "reason": "Missing outer batch dimension from matrix multiply FLOPs calculation"
            }
        ]
    }
    with open('/app/catalog/errata.json', 'w') as f:
        json.dump(errata, f, indent=2)


def create_baselines():
    baselines = {
        "1": {"mean_us": 15.0},
        "2": {"mean_us": 14.5},
        "3": {"mean_us": 150.0},
        "4": {"mean_us": 85.0},
        "5": {"mean_us": 50.0},
        "6": {"mean_us": 400.0},
        "7": {"mean_us": 70.0},
        "8": {"mean_us": 45.0},
        "9": {"mean_us": 10.0},
        "10": {"mean_us": 250.0},
        "11": {"mean_us": 320.0},
        "12": {"mean_us": 600.0},
        "13": {"mean_us": 25.0},
        "14": {"mean_us": 12.0},
        "15": {"mean_us": 11.0},
    }
    with open('/app/baselines/pytorch_baseline.json', 'w') as f:
        json.dump(baselines, f, indent=2)


def create_readme():
    readme = """GPU Kernel Benchmark Results
============================

Results from LLM-generated kernel evaluation runs on A100 GPU.

Database (benchmarks.db): Primary result store containing evaluation
runs and per-sample results. Migrated from earlier JSON-based logging.

Legacy logs (legacy/): Pre-migration JSON evaluation logs from
October 2024. The database migration covered most but not all
evaluated problems.

Problem metadata: See catalog/ directory for problem specifications.
Note: An errata file documents corrections to catalog values that
were identified after the initial data collection.

Hardware info: See hardware/ directory for GPU specifications.

Baseline timings: See baselines/ for PyTorch reference execution times.

Analysis: pipeline.py is a work-in-progress analysis script.
"""
    with open('/app/README.txt', 'w') as f:
        f.write(readme)


def create_broken_pipeline():
    code = '''#!/usr/bin/env python3
"""
Benchmark evaluation pipeline.
Produces /app/report.json with evaluation metrics.
"""
import json
import sqlite3
import csv


def load_db_results():
    """Load evaluation results from SQLite database."""
    conn = sqlite3.connect('/app/benchmarks.db')
    cursor = conn.execute(
        "SELECT problem_id, sample_id, compiled, correct, runtime_us FROM samples"
    )
    results = {}
    for row in cursor:
        pid = str(row[0])
        if pid not in results:
            results[pid] = []
        results[pid].append({
            'sample_id': row[1],
            'compiled': bool(row[2]),
            'correctness': bool(row[3]),
            'runtime': row[4] if row[4] is not None else -1.0,
        })
    conn.close()
    return results


def load_catalog():
    """Load problem catalog from CSV."""
    catalog = []
    with open('/app/catalog/problems.csv') as f:
        reader = csv.DictReader(f)
        for row in reader:
            catalog.append({
                'problem_id': int(row['problem_id']),
                'name': row['name'],
                'flops': int(row['flops']),
                'memory_bytes': int(row['memory_bytes']),
            })
    return catalog


def load_hardware():
    """Load hardware specifications from TOML."""
    import tomli
    with open('/app/hardware/system_info.toml', 'rb') as f:
        data = tomli.load(f)
    return {
        'peak_fp32_tflops': data['gpu']['compute']['peak_fp32_tflops'],
        'memory_bandwidth_gb_s': data['gpu']['memory']['bandwidth_gb_s'],
    }


def load_baselines():
    """Load PyTorch baseline timings."""
    with open('/app/baselines/pytorch_baseline.json') as f:
        return json.load(f)


def compute_pass_at_k(n, c, k):
    """Compute pass@k for a single problem."""
    if k > n:
        return None
    return min(1.0, c * k / n)


def main():
    eval_results = load_db_results()
    catalog = load_catalog()
    hw = load_hardware()
    baselines = load_baselines()

    thresholds = [0.0, 0.5, 1.0, 1.5, 2.0]
    total = len(catalog)

    fast_p = {}
    for t in thresholds:
        count = 0
        for prob in catalog:
            pid = str(prob['problem_id'])
            samples = eval_results.get(pid, [])
            greedy = [s for s in samples if s['sample_id'] == 0]
            if greedy and greedy[0]['correctness'] and greedy[0]['runtime'] > 0:
                su = baselines[pid]['mean_us'] / greedy[0]['runtime']
                if su >= t:
                    count += 1
        fast_p[str(t)] = count / total

    pak = {}
    for k in [1, 3, 5]:
        vals = []
        for prob in catalog:
            pid = str(prob['problem_id'])
            samples = eval_results.get(pid, [])
            n = len(samples)
            c = sum(1 for s in samples if s['correctness'])
            pk = compute_pass_at_k(n, c, k)
            if pk is not None:
                vals.append(pk)
        pak[str(k)] = sum(vals) / len(vals) if vals else 0.0

    report = {
        'fast_p': fast_p,
        'pass_at_k': pak,
        'geometric_mean_speedup': 0.0,
        'anomalies': [],
        'corrected_fast_p': fast_p,
        'difficulty_breakdown': {'compute_bound': 0.0, 'memory_bound': 0.0},
        'flaky_problems': [],
        'per_problem': [],
    }

    with open('/app/report.json', 'w') as f:
        json.dump(report, f, indent=2)
    print("Report written to /app/report.json")


if __name__ == '__main__':
    main()
'''
    with open('/app/pipeline.py', 'w') as f:
        f.write(code)


def main():
    create_directories()
    create_sqlite_db()
    create_legacy_logs()
    create_hardware_toml()
    create_catalog_csv()
    create_errata()
    create_baselines()
    create_readme()
    create_broken_pipeline()
    print("All data files generated under /app/")


if __name__ == '__main__':
    main()
