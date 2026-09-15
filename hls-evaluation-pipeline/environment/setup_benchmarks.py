#!/usr/bin/env python3
"""Generate HLS evaluation benchmark data for the pipeline task."""
import os
import json


def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)


BASE = "/app/benchmarks"


# ============================================================
# Problem 1: add_arrays  (7 correct / 10 total)
# ============================================================
ADD_ARRAYS_REF = """\
void add_arrays(int a[8], int b[8], int c[8]) {
    for (int i = 0; i < 8; i++) {
        c[i] = a[i] + b[i];
    }
}
"""

ADD_ARRAYS_TB = """\
#include <cstdio>
#include <cstring>
extern void add_arrays(int a[8], int b[8], int c[8]);
int main() {
    int a[8] = {1, 2, 3, 4, 5, 6, 7, 8};
    int b[8] = {10, 20, 30, 40, 50, 60, 70, 80};
    int c[8];
    memset(c, 0, sizeof(c));
    add_arrays(a, b, c);
    int expected[8] = {11, 22, 33, 44, 55, 66, 77, 88};
    for (int i = 0; i < 8; i++) {
        if (c[i] != expected[i]) return 1;
    }
    return 0;
}
"""

ADD_ARRAYS_BUGS = {
    8: """\
void add_arrays(int a[8], int b[8], int c[8]) {
    for (int i = 0; i < 7; i++) {
        c[i] = a[i] + b[i];
    }
}
""",
    9: """\
void add_arrays(int a[8], int b[8], int c[8]) {
    for (int i = 0; i < 8; i++) {
        c[i] = a[i] - b[i];
    }
}
""",
    10: """\
void add_arrays(int a[8], int b[8], int c[8]) {
    for (int i = 0; i < 8; i++) {
        c[i] = a[i] + b[7 - i];
    }
}
""",
}


# ============================================================
# Problem 2: dot_product  (4 correct / 10 total)
# ============================================================
DOT_PRODUCT_REF = """\
int dot_product(int a[8], int b[8]) {
    int result = 0;
    for (int i = 0; i < 8; i++) {
        result += a[i] * b[i];
    }
    return result;
}
"""

DOT_PRODUCT_TB = """\
#include <cstdio>
extern int dot_product(int a[8], int b[8]);
int main() {
    int a[8] = {1, 2, 3, 4, 5, 6, 7, 8};
    int b[8] = {2, 3, 4, 5, 6, 7, 8, 9};
    int result = dot_product(a, b);
    if (result != 240) return 1;
    return 0;
}
"""

DOT_PRODUCT_BUGS = {
    5: """\
int dot_product(int a[8], int b[8]) {
    int result = 0;
    for (int i = 0; i < 7; i++) {
        result += a[i] * b[i];
    }
    return result;
}
""",
    6: """\
int dot_product(int a[8], int b[8]) {
    int result = 1;
    for (int i = 0; i < 8; i++) {
        result += a[i] * b[i];
    }
    return result;
}
""",
    7: """\
int dot_product(int a[8], int b[8]) {
    int result = 0;
    for (int i = 0; i < 8; i++) {
        result += a[i] + b[i];
    }
    return result;
}
""",
    8: """\
int dot_product(int a[8], int b[8]) {
    int result = 0;
    for (int i = 0; i < 8; i++) {
        result += a[i] * b[7 - i];
    }
    return result;
}
""",
    9: """\
int dot_product(int a[8], int b[8]) {
    int result = 0;
    for (int i = 0; i < 4; i++) {
        result += a[i] * b[i];
    }
    return result;
}
""",
    10: """\
int dot_product(int a[8], int b[8]) {
    int result = 0;
    for (int i = 0; i < 8; i++) {
        result += a[i] * b[i];
    }
    return -result;
}
""",
}


# ============================================================
# Problem 3: find_max  (8 correct / 10 total)
# ============================================================
FIND_MAX_REF = """\
int find_max(int arr[16]) {
    int max_val = arr[0];
    for (int i = 1; i < 16; i++) {
        if (arr[i] > max_val) max_val = arr[i];
    }
    return max_val;
}
"""

FIND_MAX_TB = """\
#include <cstdio>
extern int find_max(int arr[16]);
int main() {
    int arr[16] = {5, 99, 8, 1, 9, 2, 7, 4, 6, 10, 0, 11, -1, 15, 12, 14};
    int result = find_max(arr);
    if (result != 99) return 1;
    return 0;
}
"""

FIND_MAX_BUGS = {
    9: """\
int find_max(int arr[16]) {
    int max_val = arr[0];
    for (int i = 1; i < 16; i++) {
        if (arr[i] < max_val) max_val = arr[i];
    }
    return max_val;
}
""",
    10: """\
int find_max(int arr[16]) {
    int max_val = arr[0];
    for (int i = 2; i < 16; i++) {
        if (arr[i] > max_val) max_val = arr[i];
    }
    return max_val;
}
""",
}


# ============================================================
# Problem 4: prefix_sum  (1 correct / 10 total)
# ============================================================
PREFIX_SUM_REF = """\
void prefix_sum(int in[16], int out[16]) {
    out[0] = in[0];
    for (int i = 1; i < 16; i++) {
        out[i] = out[i - 1] + in[i];
    }
}
"""

PREFIX_SUM_TB = """\
#include <cstdio>
#include <cstring>
extern void prefix_sum(int in[16], int out[16]);
int main() {
    int in[16] = {1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16};
    int out[16];
    memset(out, 0, sizeof(out));
    prefix_sum(in, out);
    int expected[16] = {1,3,6,10,15,21,28,36,45,55,66,78,91,105,120,136};
    for (int i = 0; i < 16; i++) {
        if (out[i] != expected[i]) return 1;
    }
    return 0;
}
"""

PREFIX_SUM_BUGS = {
    2: """\
void prefix_sum(int in[16], int out[16]) {
    out[0] = in[0];
    for (int i = 1; i < 15; i++) {
        out[i] = out[i - 1] + in[i];
    }
}
""",
    3: """\
void prefix_sum(int in[16], int out[16]) {
    for (int i = 0; i < 16; i++) {
        out[i] = in[i];
    }
}
""",
    4: """\
void prefix_sum(int in[16], int out[16]) {
    out[0] = 0;
    for (int i = 1; i < 16; i++) {
        out[i] = out[i - 1] + in[i];
    }
}
""",
    5: """\
void prefix_sum(int in[16], int out[16]) {
    out[0] = in[0];
    for (int i = 1; i < 16; i++) {
        out[i] = out[i - 1] * in[i];
    }
}
""",
    6: """\
void prefix_sum(int in[16], int out[16]) {
    out[15] = in[15];
    for (int i = 14; i >= 0; i--) {
        out[i] = out[i + 1] + in[i];
    }
}
""",
    7: """\
void prefix_sum(int in[16], int out[16]) {
    out[0] = in[0];
    for (int i = 1; i < 16; i++) {
        out[i] = out[i - 1] + out[i];
    }
}
""",
    8: """\
void prefix_sum(int in[16], int out[16]) {
    out[0] = in[0];
    for (int i = 1; i < 16; i++) {
        out[i] = out[i - 1] + in[i] + in[i - 1];
    }
}
""",
    9: """\
void prefix_sum(int in[16], int out[16]) {
    out[0] = in[0];
    for (int i = 1; i < 16; i++) {
        out[i] = out[i - 1] + in[i - 1];
    }
}
""",
    10: """\
void prefix_sum(int in[16], int out[16]) {
    for (int i = 0; i < 16; i++) {
        out[i] = 0;
    }
}
""",
}


# ============================================================
# Problem 5: hamming_dist  (0 correct / 10 total)
#   Candidates 01-05: compile but wrong results
#   Candidates 06-10: do not compile (syntax errors)
# ============================================================
HAMMING_DIST_REF = """\
int hamming_dist(unsigned int a, unsigned int b) {
    unsigned int x = a ^ b;
    int count = 0;
    while (x) {
        count += x & 1;
        x >>= 1;
    }
    return count;
}
"""

HAMMING_DIST_TB = """\
#include <cstdio>
extern int hamming_dist(unsigned int a, unsigned int b);
int main() {
    if (hamming_dist(0xFF00, 0x00FF) != 16) return 1;
    if (hamming_dist(0, 0) != 0) return 1;
    if (hamming_dist(0xFFFFFFFF, 0) != 32) return 1;
    if (hamming_dist(0xAAAAAAAA, 0x55555555) != 32) return 1;
    if (hamming_dist(3, 1) != 1) return 1;
    return 0;
}
"""

# Candidates 01-05: compile but produce wrong results
HAMMING_DIST_COMPILE_BUGS = {
    1: """\
int hamming_dist(unsigned int a, unsigned int b) {
    unsigned int x = a & b;
    int count = 0;
    while (x) { count += x & 1; x >>= 1; }
    return count;
}
""",
    2: """\
int hamming_dist(unsigned int a, unsigned int b) {
    unsigned int x = a ^ b;
    int count = 1;
    while (x) { count += x & 1; x >>= 1; }
    return count;
}
""",
    3: """\
int hamming_dist(unsigned int a, unsigned int b) {
    unsigned int x = (a ^ b) & 0xFFFF;
    int count = 0;
    while (x) { count += x & 1; x >>= 1; }
    return count;
}
""",
    4: """\
int hamming_dist(unsigned int a, unsigned int b) {
    unsigned int x = a | b;
    int count = 0;
    while (x) { count += x & 1; x >>= 1; }
    return count;
}
""",
    5: """\
int hamming_dist(unsigned int a, unsigned int b) {
    unsigned int x = a ^ b;
    int count = 0;
    for (int i = 0; i < 32; i++) {
        if (!(x & (1u << i))) count++;
    }
    return count;
}
""",
}

# Candidates 06-10: syntax errors, do not compile
HAMMING_DIST_SYNTAX_BUGS = {
    6: """\
int hamming_dist(unsigned int a, unsigned int b) {
    unsigned int x = a ^ b
    int count = 0;
    while (x) { count += x & 1; x >>= 1; }
    return count;
}
""",
    7: """\
int hamming_dist(unsigned int a, unsigned int b) {
    uint32 x = a ^ b;
    int count = 0;
    while (x) { count += x & 1; x >>= 1; }
    return count;
}
""",
    8: """\
int hamming_dist(unsigned int a, unsigned int b) {
    unsigned int x = a ^ b;
    int count = 0;
    while (x) { count += x & 1; x >>= 1;
    return count;
}
""",
    9: """\
int hamming_dist(unsigned int a, unsigned int b) {
    unsigned int x = a ^ b;
    int count = 0;
    while (x) { count += x & 1; x >>= 1; }
    return count
}
""",
    10: """\
int hamming_dist(unsigned int a, unsigned int b) {
    unsigned int x = a ^ b;
    int count = 0;
    while (x {
        count += x & 1;
        x >>= 1;
    }
    return count;
}
""",
}


# ============================================================
# Instructions for each benchmark
# ============================================================
INSTRUCTIONS = {
    "add_arrays": (
        "Implement a function `void add_arrays(int a[8], int b[8], int c[8])` "
        "that computes element-wise addition of two 8-element integer arrays, "
        "storing results in output array c."
    ),
    "dot_product": (
        "Implement a function `int dot_product(int a[8], int b[8])` that "
        "computes and returns the dot product of two 8-element integer arrays."
    ),
    "find_max": (
        "Implement a function `int find_max(int arr[16])` that returns the "
        "maximum value in a 16-element integer array."
    ),
    "prefix_sum": (
        "Implement a function `void prefix_sum(int in[16], int out[16])` that "
        "computes the prefix sum (inclusive scan) of a 16-element integer array."
    ),
    "hamming_dist": (
        "Implement a function `int hamming_dist(unsigned int a, unsigned int b)` "
        "that returns the Hamming distance (number of differing bit positions) "
        "between two unsigned 32-bit integers."
    ),
}


# ============================================================
# Problem definitions: (reference, testbench, correct_count, bug_dict)
# ============================================================
PROBLEMS = {
    "add_arrays": (ADD_ARRAYS_REF, ADD_ARRAYS_TB, 7, ADD_ARRAYS_BUGS),
    "dot_product": (DOT_PRODUCT_REF, DOT_PRODUCT_TB, 4, DOT_PRODUCT_BUGS),
    "find_max": (FIND_MAX_REF, FIND_MAX_TB, 8, FIND_MAX_BUGS),
    "prefix_sum": (PREFIX_SUM_REF, PREFIX_SUM_TB, 1, PREFIX_SUM_BUGS),
}


def generate_benchmarks():
    """Generate all benchmark C++ files."""
    # Standard problems (compile + possible sim failures)
    for name, (ref, tb, n_correct, bugs) in PROBLEMS.items():
        bdir = f"{BASE}/{name}"
        write_file(f"{bdir}/reference.cpp", ref)
        write_file(f"{bdir}/testbench.cpp", tb)
        write_file(f"{bdir}/instruction.txt", INSTRUCTIONS[name])

        for i in range(1, 11):
            cpath = f"{bdir}/candidates/candidate_{i:02d}.cpp"
            if i in bugs:
                write_file(cpath, bugs[i])
            else:
                write_file(cpath, ref)

    # hamming_dist: special handling (compile + sim bugs, plus syntax bugs)
    name = "hamming_dist"
    bdir = f"{BASE}/{name}"
    write_file(f"{bdir}/reference.cpp", HAMMING_DIST_REF)
    write_file(f"{bdir}/testbench.cpp", HAMMING_DIST_TB)
    write_file(f"{bdir}/instruction.txt", INSTRUCTIONS[name])

    for i in range(1, 6):
        write_file(
            f"{bdir}/candidates/candidate_{i:02d}.cpp",
            HAMMING_DIST_COMPILE_BUGS[i],
        )
    for i in range(6, 11):
        write_file(
            f"{bdir}/candidates/candidate_{i:02d}.cpp",
            HAMMING_DIST_SYNTAX_BUGS[i],
        )


def generate_dse_config():
    """Generate DSE configuration as JSON."""
    dse_config = {
        "parameters": {
            "clock_period_ns": [3.3, 5.0],
            "enable_pipeline": [True, False],
            "pipeline_ii": [1, 2],
            "enable_dataflow": [True, False],
            "unroll_factor": [1, 2, 4, 8],
            "array_partition_factor": [1, 2, 4],
            "allocation_limit_add": [0, 1, 2],
            "dsp_full_reg": [True, False],
            "vivado_strategy": ["Default", "Performance_Explore", "Area_Explore"],
        },
        "constraints": [
            {
                "dependent": "pipeline_ii",
                "requires": {"enable_pipeline": True},
            },
            {
                "dependent": "array_partition_factor",
                "requires": {"unroll_factor": [2, 4, 8]},
            },
            {
                "dependent": "allocation_limit_add",
                "requires": {"enable_dataflow": True},
            },
        ],
    }
    write_file(
        "/app/dse_config.json",
        json.dumps(dse_config, indent=2) + "\n",
    )


def generate_ppa_data():
    """Generate PPA analysis data files."""
    ppa_dir = "/app/ppa_analysis"

    # --- Pareto analysis design points ---
    # d01-d05: Pareto-optimal (not dominated by any other)
    # d06-d15: each dominated by at least one of d01-d05
    design_points = [
        {"id": "d01", "lut": 70,  "ff": 90,  "latency_ns": 60.0, "power_mw": 8.0},
        {"id": "d02", "lut": 60,  "ff": 95,  "latency_ns": 50.0, "power_mw": 12.0},
        {"id": "d03", "lut": 85,  "ff": 60,  "latency_ns": 55.0, "power_mw": 15.0},
        {"id": "d04", "lut": 90,  "ff": 85,  "latency_ns": 35.0, "power_mw": 18.0},
        {"id": "d05", "lut": 110, "ff": 80,  "latency_ns": 30.0, "power_mw": 22.0},
        {"id": "d06", "lut": 75,  "ff": 95,  "latency_ns": 65.0, "power_mw": 10.0},
        {"id": "d07", "lut": 65,  "ff": 100, "latency_ns": 55.0, "power_mw": 14.0},
        {"id": "d08", "lut": 90,  "ff": 65,  "latency_ns": 58.0, "power_mw": 17.0},
        {"id": "d09", "lut": 95,  "ff": 90,  "latency_ns": 40.0, "power_mw": 20.0},
        {"id": "d10", "lut": 115, "ff": 85,  "latency_ns": 35.0, "power_mw": 25.0},
        {"id": "d11", "lut": 80,  "ff": 98,  "latency_ns": 62.0, "power_mw": 11.0},
        {"id": "d12", "lut": 100, "ff": 95,  "latency_ns": 45.0, "power_mw": 19.0},
        {"id": "d13", "lut": 120, "ff": 88,  "latency_ns": 38.0, "power_mw": 24.0},
        {"id": "d14", "lut": 72,  "ff": 92,  "latency_ns": 63.0, "power_mw": 9.0},
        {"id": "d15", "lut": 130, "ff": 100, "latency_ns": 32.0, "power_mw": 26.0},
    ]
    write_file(
        f"{ppa_dir}/design_points.json",
        json.dumps(design_points, indent=2) + "\n",
    )

    # --- PPA comparison data for normalization ---
    ppa_comparison = {
        "add_arrays": {
            "reference": {"lut": 100, "ff": 80, "latency_ns": 50.0, "power_mw": 10.0},
            "generated": {"lut": 120, "ff": 100, "latency_ns": 40.0, "power_mw": 12.0},
        },
        "dot_product": {
            "reference": {"lut": 200, "ff": 160, "latency_ns": 100.0, "power_mw": 20.0},
            "generated": {"lut": 180, "ff": 170, "latency_ns": 90.0, "power_mw": 22.0},
        },
        "find_max": {
            "reference": {"lut": 50, "ff": 40, "latency_ns": 25.0, "power_mw": 5.0},
            "generated": {"lut": 55, "ff": 44, "latency_ns": 30.0, "power_mw": 4.5},
        },
    }
    write_file(
        f"{ppa_dir}/ppa_comparison.json",
        json.dumps(ppa_comparison, indent=2) + "\n",
    )


def generate_eval_spec():
    """Generate the evaluation specification file."""
    spec = {
        "description": "Bench4HLS Evaluation Pipeline Report",
        "output_path": "/app/output/report.json",
        "notes": "Each benchmark has n=10 candidate implementations. Pareto-optimal IDs must be alphabetically sorted.",
        "sections": {
            "compilation": {
                "format": "{benchmark_name: {candidate_name: bool}}",
                "description": "Compilation status for each candidate against its testbench via g++",
            },
            "simulation": {
                "format": "{benchmark_name: {candidate_name: bool}}",
                "description": "Functional correctness — run compiled binary; true if exit code 0. Compilation failures are false.",
            },
            "dse": {
                "fields": {
                    "total_configurations": "int — valid configurations after enforcing dependency constraints from dse_config.json",
                    "unconstrained_total": "int — full Cartesian product size ignoring all constraints",
                },
            },
            "pass_at_k": {
                "fields": {
                    "per_benchmark": "{benchmark_name: {pass_at_1: float, pass_at_5: float, pass_at_10: float}}",
                    "aggregate": "{pass_at_1: float, pass_at_5: float, pass_at_10: float} — arithmetic mean across benchmarks",
                },
                "description": "Unbiased Pass@k estimator for code generation evaluation (n=10, k in {1,5,10})",
            },
            "pareto_frontier": {
                "fields": {
                    "optimal_set": "list[str] — non-dominated design point IDs (minimize all four PPA objectives)",
                    "num_dominated": "int — count of dominated points",
                },
            },
            "ppa_normalization": {
                "format": "{benchmark_name: {lut_pct: float, ff_pct: float, latency_pct: float, power_pct: float}}",
                "description": "Signed percentage change of generated vs. reference for each PPA metric",
            },
        },
    }
    write_file("/app/evaluation_spec.json", json.dumps(spec, indent=2) + "\n")


if __name__ == "__main__":
    generate_benchmarks()
    generate_dse_config()
    generate_ppa_data()
    generate_eval_spec()
    print("Benchmark data generated successfully.")
