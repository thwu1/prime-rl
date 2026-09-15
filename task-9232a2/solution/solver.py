#!/usr/bin/env python3

"""
Solution for MoE Inference Cluster Capacity Analysis.

Reads the benchmark database and FlashMLA source code to produce analysis.json.
"""
import json
import math
import sqlite3


def get_kv_bytes_per_token(layout_type: str, d_nope: int, d_rope: int) -> int:
    """
    Compute KV cache bytes per token per layer based on the layout type.

    Derived from flashmla_quant.py:
    - V32_FP8Sparse: d_nope FP8 + num_tiles*4 scale bytes + 2*d_rope rope bytes
      where tile_size=128, num_tiles=d_nope//128
    - MODEL1_FP8Sparse: d_nope FP8 + 2*d_rope rope-as-fp8-view + num_tiles+1 scale bytes
      where tile_size=64, num_tiles=d_nope//64
    - bf16: full latent vector as bfloat16 = (d_nope + d_rope) * 2
    """
    if layout_type == "bf16":
        return (d_nope + d_rope) * 2
    elif layout_type == "V32_FP8Sparse":
        tile_size = 128
        num_tiles = d_nope // tile_size
        input_elem_size = 2  # bfloat16
        return d_nope + num_tiles * 4 + input_elem_size * d_rope
    elif layout_type == "MODEL1_FP8Sparse":
        tile_size = 64
        num_tiles = d_nope // tile_size
        return d_nope + 2 * d_rope + num_tiles + 1
    else:
        raise ValueError(f"Unknown layout type: {layout_type}")


def main():
    db = sqlite3.connect("/app/cluster.db")
    db.row_factory = sqlite3.Row

    # Query all workloads with joined model, GPU, and format data
    query = """
    SELECT
        w.id, w.name, w.batch_size, w.seq_len, w.use_fp8_dispatch,
        m.num_layers, m.hidden_dim, m.num_heads,
        m.d_nope, m.d_rope, m.d_v,
        m.num_experts, m.topk, m.ffn_intermediate, m.weight_memory_gb,
        g.id AS gpu_id, g.sm_count, g.memory_gb,
        g.hbm_bandwidth_gbps, g.peak_bf16_tflops,
        k.layout_type
    FROM workloads w
    JOIN model_configs m ON w.model_config_id = m.id
    JOIN gpu_specs g ON w.gpu_spec_id = g.id
    JOIN kv_cache_formats k ON w.kv_format_id = k.id
    ORDER BY w.id
    """
    workloads = db.execute(query).fetchall()

    results = []
    for w in workloads:
        d_qk = w["d_nope"] + w["d_rope"]

        # 1. KV bytes per token from source code layout
        kv_bpt = get_kv_bytes_per_token(
            w["layout_type"], w["d_nope"], w["d_rope"]
        )

        # 2. Total KV memory in GB (1 GB = 1e9 bytes)
        total_kv_gb = (
            w["batch_size"] * w["seq_len"] * kv_bpt * w["num_layers"] / 1e9
        )

        # 3. Max batch size fitting in GPU memory
        available_bytes = (w["memory_gb"] - w["weight_memory_gb"]) * 1e9
        per_batch_bytes = w["seq_len"] * kv_bpt * w["num_layers"]
        max_batch = int(available_bytes / per_batch_bytes)

        # 4. Does the configured batch fit?
        fits = w["batch_size"] <= max_batch

        # 5. MoE FLOPs per token per layer
        #    SwiGLU: gate(2*H*I) + up(2*H*I) + down(2*I*H) = 6*H*I per expert
        moe_flops = w["topk"] * 6 * w["hidden_dim"] * w["ffn_intermediate"]

        # 6. Attention FLOPs per token per layer (decoding)
        #    QK: 2 * num_heads * d_qk * seq_len
        #    PV: 2 * num_heads * seq_len * d_v
        attn_flops = 2 * w["num_heads"] * w["seq_len"] * (d_qk + w["d_v"])

        # 7. Arithmetic intensity (FLOP/byte)
        kv_bytes_loaded = w["seq_len"] * kv_bpt
        intensity = round(attn_flops / kv_bytes_loaded, 1)

        # 8. EP dispatch volume in MB
        elem_size = 1 if w["use_fp8_dispatch"] else 2
        ep_volume_mb = round(
            w["batch_size"] * w["topk"] * w["hidden_dim"] * elem_size / 1e6,
            6,
        )

        # 9. Minimum EP SMs for >= 90% of peak dispatch bandwidth
        ep_rows = db.execute(
            "SELECT num_sms, dispatch_bw_gbps FROM ep_measurements "
            "WHERE gpu_spec_id = ? ORDER BY num_sms ASC",
            (w["gpu_id"],),
        ).fetchall()
        peak_bw = max(r["dispatch_bw_gbps"] for r in ep_rows)
        threshold = 0.9 * peak_bw
        min_ep_sms = None
        for row in ep_rows:
            if row["dispatch_bw_gbps"] >= threshold:
                min_ep_sms = row["num_sms"]
                break

        # 10. Available compute SMs
        available_sms = w["sm_count"] - min_ep_sms

        results.append(
            {
                "workload_id": w["id"],
                "workload_name": w["name"],
                "kv_bytes_per_token": kv_bpt,
                "total_kv_memory_gb": total_kv_gb,
                "max_batch_size": max_batch,
                "fits_in_memory": fits,
                "moe_flops_per_token": moe_flops,
                "attn_flops_per_token": attn_flops,
                "attn_arithmetic_intensity": intensity,
                "ep_dispatch_volume_mb": ep_volume_mb,
                "min_ep_sms_90pct": min_ep_sms,
                "available_compute_sms": available_sms,
            }
        )

    with open("/app/analysis.json", "w") as f:
        json.dump(results, f, indent=2)

    db.close()
    print(f"Wrote analysis for {len(results)} workloads to /app/analysis.json")


if __name__ == "__main__":
    main()
