#!/usr/bin/env python3
import sqlite3
import json

db = sqlite3.connect("/app/parallel_costs.db")
c = db.cursor()

with open("/app/schema.sql") as f:
    c.executescript(f.read())

c.executemany("INSERT INTO algorithms VALUES (?,?,?,?)", [
    (1, "reduce", "Parallel reduce (sum) of a sequence of length n", "n must be a power of 2"),
    (2, "scan", "Parallel prefix sums (scan) of a sequence of length n", "n must be a power of 2"),
    (3, "mergesort", "Parallel merge sort with parallel merge step", "n must be a power of 2"),
    (4, "standard_matmul", "Standard recursive matrix multiplication for n x n matrices", "n must be a power of 2"),
    (5, "strassen_matmul", "Strassen matrix multiplication for n x n matrices", "n must be a power of 2"),
    (6, "karatsuba", "Karatsuba algorithm for multiplication of n-digit integers", "n must be a power of 2"),
])

c.executemany("INSERT INTO work_recurrences VALUES (?,?,?,?)", [
    (1, 2, 2, "1"),
    (2, 2, 2, "2"),
    (3, 2, 2, "3*n"),
    (4, 8, 2, "4*n*n"),
    (5, 7, 2, "18*n*n"),
    (6, 3, 2, "4*n"),
])

c.executemany("INSERT INTO span_recurrences VALUES (?,?,?,?)", [
    (1, 1, 2, "1"),
    (2, 1, 2, "2"),
    (3, 1, 2, "log2(n)"),
    (4, 1, 2, "log2(n)"),
    (5, 1, 2, "log2(n)"),
    (6, 1, 2, "log2(n)"),
])

c.executemany("INSERT INTO base_cases VALUES (?,?,?,?)", [
    (1, "n <= 1", 0, 0),
    (2, "n <= 1", 0, 0),
    (3, "n <= 1", 0, 0),
    (4, "n <= 1", 1, 0),
    (5, "n <= 1", 1, 0),
    (6, "n <= 1", 1, 0),
])

queries = [
    (1, "evaluate", "Compute work and span for parallel reduce on 2^20 elements",
     json.dumps({"algorithm": "reduce", "n": 1048576, "output_fields": ["work", "span"]})),
    (2, "evaluate", "Compute work and span for parallel scan on 2^16 elements",
     json.dumps({"algorithm": "scan", "n": 65536, "output_fields": ["work", "span"]})),
    (3, "evaluate", "Compute work and span for parallel merge sort on 2^18 elements",
     json.dumps({"algorithm": "mergesort", "n": 262144, "output_fields": ["work", "span"]})),
    (4, "evaluate", "Compute work and span for standard matrix multiplication on 32x32",
     json.dumps({"algorithm": "standard_matmul", "n": 32, "output_fields": ["work", "span"]})),
    (5, "evaluate", "Compute work and span for Strassen matrix multiplication on 32x32",
     json.dumps({"algorithm": "strassen_matmul", "n": 32, "output_fields": ["work", "span"]})),
    (6, "evaluate", "Compute work and span for Karatsuba on 2^15-digit numbers",
     json.dumps({"algorithm": "karatsuba", "n": 32768, "output_fields": ["work", "span"]})),
    (7, "brent", "Brent's theorem for mergesort on 2^20 with 128 processors",
     json.dumps({"algorithm": "mergesort", "n": 1048576, "processors": 128, "output_fields": ["T_P"]})),
    (8, "brent", "Brent's theorem for reduce on 2^20 with 4 processors",
     json.dumps({"algorithm": "reduce", "n": 1048576, "processors": 4, "output_fields": ["T_P"]})),
    (9, "brent", "Brent's theorem for standard matmul on 256x256 with 16 processors",
     json.dumps({"algorithm": "standard_matmul", "n": 256, "processors": 16, "output_fields": ["T_P"]})),
    (10, "composition", "Pipeline: mergesort then reduce on 2^20",
     json.dumps({"pipeline": ["mergesort", "reduce"], "n": 1048576, "output_fields": ["work", "span"]})),
    (11, "composition", "Pipeline: scan then reduce on 2^16",
     json.dumps({"pipeline": ["scan", "reduce"], "n": 65536, "output_fields": ["work", "span"]})),
    (12, "crossover", "Find crossover where Strassen beats standard matmul in work",
     json.dumps({"algorithms": ["standard_matmul", "strassen_matmul"], "metric": "work", "output_fields": ["n"]})),
    (13, "optimal_processors", "Minimum processors for reduce within 10% of span bound",
     json.dumps({"algorithm": "reduce", "n": 1048576, "overhead_factor": 1.1, "output_fields": ["processors"]})),
    (14, "min_parallelism_n", "Minimum n where mergesort parallelism exceeds 10000",
     json.dumps({"algorithm": "mergesort", "min_parallelism": 10000, "output_fields": ["n"]})),
    (15, "granularity", "Granularity optimization for hybrid mergesort with 64 processors",
     json.dumps({"algorithm": "mergesort", "n": 1048576, "processors": 64,
                  "sequential_base": {"work_formula": "m * log2(m)", "span_equals_work": True},
                  "output_fields": ["threshold", "T_P"]})),
    (16, "composition_brent", "Three-stage pipeline (scan, mergesort, reduce) with Brent",
     json.dumps({"pipeline": ["scan", "mergesort", "reduce"], "n": 1048576, "processors": 256,
                  "output_fields": ["T_P"]})),
    (17, "pipeline_granularity", "Optimize mergesort granularity within scan-mergesort-reduce pipeline",
     json.dumps({"pipeline": ["scan", "mergesort", "reduce"], "optimize_stage": "mergesort",
                  "n": 262144, "processors": 256,
                  "sequential_base": {"work_formula": "m * log2(m)", "span_equals_work": True},
                  "output_fields": ["threshold", "T_P"]})),
    (18, "efficiency_threshold", "Largest power-of-2 processors maintaining 50% parallel efficiency for mergesort",
     json.dumps({"algorithm": "mergesort", "n": 1048576, "min_efficiency": 0.5,
                  "output_fields": ["processors"]})),
    (19, "strassen_granularity", "Granularity for Strassen with cubic sequential base on 64x64",
     json.dumps({"algorithm": "strassen_matmul", "n": 64, "processors": 16,
                  "sequential_base": {"work_formula": "m * m * m", "span_equals_work": True},
                  "output_fields": ["threshold", "T_P"]})),
]
c.executemany("INSERT INTO queries VALUES (?,?,?,?)", queries)

db.commit()
db.close()
