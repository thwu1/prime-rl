#!/usr/bin/env python3
"""
Transformer attention roofline performance analyzer — reference solution.

"""

import json
import math


def compute_attention_flops(b, h, lq, lkv, d_qk, d_v):
    """
    Attention FLOPs per layer.
    QK^T: 2 * b * h * lq * lkv * d_qk  (h query heads, each does a matmul)
    S*V:  2 * b * h * lq * lkv * d_v
    """
    return 2 * b * h * lq * lkv * d_qk + 2 * b * h * lq * lkv * d_v


def compute_attention_memory(b, h, h_kv, lq, lkv, d_qk, d_v, dtype_bytes):
    """
    Attention HBM memory bytes per layer.
    Read Q:  b * h * lq * d_qk     (all h query heads)
    Read K:  b * h_kv * lkv * d_qk (only h_kv KV heads, shared across groups)
    Read V:  b * h_kv * lkv * d_v
    Write O: b * h * lq * d_v      (all h output heads)
    """
    return dtype_bytes * (
        b * h * lq * d_qk
        + b * h_kv * lkv * d_qk
        + b * h_kv * lkv * d_v
        + b * h * lq * d_v
    )


def compute_kv_cache_bytes(b, h_kv, lkv, d_head, dtype_bytes, n_layers):
    """Total KV cache bytes across all layers and batch elements."""
    # 2 for key + value
    return 2 * b * n_layers * h_kv * lkv * d_head * dtype_bytes


def main():
    with open("/data/config.json") as f:
        config = json.load(f)

    hw = config["hardware"]
    peak_tflops = hw["peak_tflops"]
    bw_gb_s = hw["bandwidth_gb_s"]
    bw_bytes_s = bw_gb_s * 1e9
    peak_flops = peak_tflops * 1e12
    ridge_point = peak_flops / bw_bytes_s

    report = {"ridge_point": ridge_point, "scenarios": {}}

    # Process each scenario
    for scenario in config["scenarios"]:
        name = scenario["name"]
        h = scenario["n_heads"]
        h_kv = scenario["n_kv_heads"]
        d = scenario["d_head"]
        n_layers = scenario["n_layers"]
        dtype = scenario["dtype_bytes"]
        b = scenario["batch_size"]
        lq = scenario["seq_len_q"]
        lkv = scenario["seq_len_kv"]

        flops = compute_attention_flops(b, h, lq, lkv, d, d)
        mem = compute_attention_memory(b, h, h_kv, lq, lkv, d, d, dtype)
        ai = flops / mem
        achievable_flops = min(ai * bw_bytes_s, peak_flops)
        roofline_tflops = achievable_flops / 1e12
        is_memory_bound = ai < ridge_point
        kv_cache = compute_kv_cache_bytes(b, h_kv, lkv, d, dtype, n_layers)

        report["scenarios"][name] = {
            "attention_flops": flops,
            "attention_memory_bytes": mem,
            "arithmetic_intensity": ai,
            "roofline_tflops": roofline_tflops,
            "is_memory_bound": is_memory_bound,
            "kv_cache_bytes": kv_cache,
        }

    # Critical prefill sequence length
    cp = config["analysis"]["critical_prefill"]
    h_cp = cp["n_heads"]
    h_kv_cp = cp["n_kv_heads"]
    d_cp = cp["d_head"]
    dtype_cp = cp["dtype_bytes"]
    # For prefill: lq = lkv = L, batch=1
    # AI = 2*h*L*L / (dtype * (h*L + h_kv*L)) = 2*h*L / (dtype*(h + h_kv))
    # Need AI >= ridge_point
    # L >= ridge_point * dtype * (h + h_kv) / (2 * h)
    min_L = ridge_point * dtype_cp * (h_cp + h_kv_cp) / (2 * h_cp)
    report["critical_prefill_seq_len"] = math.ceil(min_L)

    # Group size analysis
    gs = config["analysis"]["group_size_sweep"]
    h_gs = gs["n_heads"]
    d_gs = gs["d_head"]
    dtype_gs = gs["dtype_bytes"]
    lq_gs = gs["seq_len_q"]
    lkv_gs = gs["seq_len_kv"]

    group_analysis = {}
    for g in range(1, h_gs + 1):
        if h_gs % g != 0:
            continue
        h_kv_g = h_gs // g
        flops_g = compute_attention_flops(1, h_gs, lq_gs, lkv_gs, d_gs, d_gs)
        mem_g = compute_attention_memory(1, h_gs, h_kv_g, lq_gs, lkv_gs, d_gs, d_gs, dtype_gs)
        ai_g = flops_g / mem_g
        group_analysis[str(g)] = ai_g

    report["group_size_analysis"] = group_analysis

    with open("/app/report.json", "w") as f:
        json.dump(report, f, indent=2)

    print("Report written to /app/report.json")


if __name__ == "__main__":
    main()
