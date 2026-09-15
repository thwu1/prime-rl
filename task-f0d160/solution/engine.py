#!/usr/bin/env python3
"""
Multi-GPU attention workload placement engine.

Evaluates transformer attention workloads across multiple GPUs using
roofline performance analysis and produces an optimal placement report.

"""

import ctypes
import json
import math
import sqlite3

DTYPE_BYTES_MAP = {"fp16": 2, "bf16": 2, "fp32": 4, "fp8": 1}


def load_roofline_lib():
    """Load the C roofline shared library with proper type signatures."""
    lib = ctypes.CDLL("/app/libroofline.so")
    lib.gb_to_bytes.argtypes = [ctypes.c_double]
    lib.gb_to_bytes.restype = ctypes.c_double
    lib.achievable_flops.argtypes = [ctypes.c_double, ctypes.c_double, ctypes.c_double]
    lib.achievable_flops.restype = ctypes.c_double
    lib.compute_ridge_point.argtypes = [ctypes.c_double, ctypes.c_double]
    lib.compute_ridge_point.restype = ctypes.c_double
    return lib


def load_gpus():
    """Load all GPU specs from the SQLite database."""
    conn = sqlite3.connect("/app/data/hardware.db")
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT name, peak_tflops, bandwidth_gb_s, memory_gb FROM gpu_specs"
    ).fetchall()
    conn.close()
    return {row["name"]: dict(row) for row in rows}


def attention_flops(b, h, lq, lkv, d):
    """
    Compute total attention FLOPs for one layer.
    QK^T: 2*b*h*lq*lkv*d  (each FMA = 2 FLOPs)
    S*V:  2*b*h*lq*lkv*d
    """
    return 2 * b * h * lq * lkv * d + 2 * b * h * lq * lkv * d


def attention_memory(b, h, h_kv, lq, lkv, d, dtype_bytes):
    """
    Compute total HBM bytes accessed for one attention layer.
    Q: h query heads, K: h_kv KV heads, V: h_kv KV heads, O: h query heads.
    """
    return dtype_bytes * (
        b * h * lq * d
        + b * h_kv * lkv * d
        + b * h_kv * lkv * d
        + b * h * lq * d
    )


def kv_cache_bytes(b, h_kv, lkv, d, dtype_bytes, n_layers):
    """
    Compute total KV cache memory across all layers.
    Factor of 2 for both key and value tensors.
    """
    return 2 * b * n_layers * h_kv * lkv * d * dtype_bytes


def main():
    lib = load_roofline_lib()
    gpus = load_gpus()

    with open("/app/data/scenarios.json") as f:
        scenarios = json.load(f)
    with open("/app/data/analysis.json") as f:
        analysis = json.load(f)

    report = {
        "gpus": {},
        "scenarios": {},
        "critical_prefill_seq_lens": {},
        "group_size_analysis": {},
    }

    # Precompute per-GPU derived values
    gpu_derived = {}
    for gname, g in gpus.items():
        bw_bytes = lib.gb_to_bytes(float(g["bandwidth_gb_s"]))
        peak_flops = g["peak_tflops"] * 1e12
        ridge = lib.compute_ridge_point(peak_flops, bw_bytes)
        report["gpus"][gname] = {"ridge_point": ridge}
        gpu_derived[gname] = {
            "bw_bytes": bw_bytes,
            "peak_flops": peak_flops,
            "ridge": ridge,
        }

    # Evaluate each scenario on every GPU
    for sname, s in scenarios.items():
        dtype = DTYPE_BYTES_MAP[s["dtype"]]
        b = s["batch_size"]
        h = s["n_heads"]
        h_kv = s["n_kv_heads"]
        lq = s["seq_len_q"]
        lkv = s["seq_len_kv"]
        d = s["d_head"]
        n_layers = s["n_layers"]

        flops = attention_flops(b, h, lq, lkv, d)
        mem = attention_memory(b, h, h_kv, lq, lkv, d, dtype)
        ai = flops / mem
        kv = kv_cache_bytes(b, h_kv, lkv, d, dtype, n_layers)

        gpu_eval = {}
        for gname, g in gpus.items():
            gd = gpu_derived[gname]
            achievable = lib.achievable_flops(
                float(ai), gd["bw_bytes"], gd["peak_flops"]
            )
            roofline_tf = achievable / 1e12
            is_mb = ai < gd["ridge"]
            fits = kv <= g["memory_gb"] * 1e9

            gpu_eval[gname] = {
                "roofline_tflops": roofline_tf,
                "is_memory_bound": is_mb,
                "kv_cache_fits": fits,
            }

        # Select optimal GPU: highest roofline among feasible,
        # ties broken by peak_tflops descending then name ascending
        feasible = [
            (gn, gpu_eval[gn])
            for gn in gpu_eval
            if gpu_eval[gn]["kv_cache_fits"]
        ]
        feasible.sort(
            key=lambda x: (
                -x[1]["roofline_tflops"],
                -gpus[x[0]]["peak_tflops"],
                x[0],
            )
        )
        optimal = feasible[0][0] if feasible else None

        report["scenarios"][sname] = {
            "attention_flops": flops,
            "attention_memory_bytes": mem,
            "arithmetic_intensity": ai,
            "kv_cache_bytes": kv,
            "gpu_evaluation": gpu_eval,
            "optimal_gpu": optimal,
        }

    # Critical prefill sequence lengths per GPU
    cp = analysis["critical_prefill"]
    h_cp = cp["n_heads"]
    h_kv_cp = cp["n_kv_heads"]
    dtype_cp = DTYPE_BYTES_MAP[cp["dtype"]]

    for gname in gpus:
        ridge = gpu_derived[gname]["ridge"]
        # For prefill (lq=lkv=L, b=1):
        # AI(L) = 2*h*L / (dtype*(h + h_kv))
        # Solve AI >= ridge  =>  L >= ridge*dtype*(h+h_kv) / (2*h)
        min_L = ridge * dtype_cp * (h_cp + h_kv_cp) / (2 * h_cp)
        report["critical_prefill_seq_lens"][gname] = math.ceil(min_L)

    # Group size analysis (GPU-independent arithmetic intensities)
    gs = analysis["group_size_sweep"]
    h_gs = gs["n_heads"]
    d_gs = gs["d_head"]
    dtype_gs = DTYPE_BYTES_MAP[gs["dtype"]]
    b_gs = gs.get("batch_size", 1)
    lq_gs = gs.get("seq_len_q", 1)
    lkv_gs = gs["seq_len_kv"]

    for g_val in range(1, h_gs + 1):
        if h_gs % g_val != 0:
            continue
        h_kv_g = h_gs // g_val
        f = attention_flops(b_gs, h_gs, lq_gs, lkv_gs, d_gs)
        m = attention_memory(b_gs, h_gs, h_kv_g, lq_gs, lkv_gs, d_gs, dtype_gs)
        report["group_size_analysis"][str(g_val)] = f / m

    with open("/app/report.json", "w") as f:
        json.dump(report, f, indent=2)

    print("Report written to /app/report.json")


if __name__ == "__main__":
    main()
