#!/usr/bin/env python3

"""
Flash Attention Cluster Deployment Analyzer.

Reads cluster data from SQLite, architecture config from TOML, workload specs
from CSV, analyzes Flash Attention source code logic, computes deployment
metrics, evaluates cost-efficiency, and produces an optimal deployment plan.
"""

import csv
import json
import math
import sqlite3
import tomllib


def query_nodes(db_path):
    """Extract node data from SQLite database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM nodes")
    nodes = [dict(row) for row in cur.fetchall()]
    conn.close()
    return nodes


def parse_workloads(csv_path):
    """Parse workload configurations from CSV file."""
    workloads = []
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            workloads.append({
                "name": row["name"],
                "batch_size": int(row["batch_size"]),
                "seq_len": int(row["seq_len"]),
                "nheads": int(row["nheads"]),
                "headdim": int(row["headdim"]),
                "causal": row["causal"].lower() == "true",
                "dtype_bytes": int(row["dtype_bytes"]),
                "dropout": row["dropout"].lower() == "true",
            })
    return workloads


def load_config(toml_path):
    """Load cluster configuration from TOML file."""
    with open(toml_path, "rb") as f:
        return tomllib.load(f)


def parse_version(version_str):
    return tuple(int(p) for p in version_str.strip().split("."))


def version_gte(version_str, target):
    return parse_version(version_str) >= parse_version(target)


def generate_gencodes(cuda_version, archs):
    archs = set(archs)
    cc_flag = []

    if "80" in archs:
        cc_flag += ["-gencode", "arch=compute_80,code=sm_80"]

    if version_gte(cuda_version, "11.8") and "90" in archs:
        cc_flag += ["-gencode", "arch=compute_90,code=sm_90"]

    if version_gte(cuda_version, "12.8"):
        if "100" in archs:
            if version_gte(cuda_version, "12.9"):
                cc_flag += ["-gencode", "arch=compute_100f,code=sm_100"]
            else:
                cc_flag += ["-gencode", "arch=compute_100,code=sm_100"]

        if "120" in archs:
            if version_gte(cuda_version, "12.9"):
                cc_flag += ["-gencode", "arch=compute_120f,code=sm_120"]
            else:
                cc_flag += ["-gencode", "arch=compute_120,code=sm_120"]

        if "110" in archs:
            if version_gte(cuda_version, "13.0"):
                cc_flag += ["-gencode", "arch=compute_110f,code=sm_110"]
            else:
                if version_gte(cuda_version, "12.8"):
                    cc_flag += ["-gencode", "arch=compute_101,code=sm_101"]

    numeric = [a for a in archs if a.isdigit()]
    if numeric:
        newest = max(numeric, key=int)
        cc_flag += ["-gencode", f"arch=compute_{newest},code=compute_{newest}"]

    return cc_flag


def compute_max_build_jobs(cpu_cores, system_memory_gb, nvcc_threads):
    nvcc_threads = max(1, int(nvcc_threads))
    max_num_jobs_cores = max(1, cpu_cores // 2)
    max_num_jobs_memory = max(1, int(system_memory_gb / (5 * nvcc_threads)))
    return max(1, min(max_num_jobs_cores, max_num_jobs_memory))


def get_block_size_n(compute_capability, head_dim, is_dropout, is_causal):
    assert head_dim <= 256
    major, minor = compute_capability
    is_sm8x = major == 8 and minor > 0

    if head_dim <= 32:
        return 128
    if head_dim <= 64:
        return 128 if not is_dropout else 64
    elif head_dim <= 96:
        return 64
    elif head_dim <= 128:
        if is_sm8x:
            return 64 if (not is_dropout and is_causal) else 32
        else:
            return 64 if not is_dropout else 32
    elif head_dim <= 192:
        return 64
    elif head_dim <= 224:
        return 64
    elif head_dim <= 256:
        return 64


def compute_fwd_flops(batch, seqlen, headdim, nheads, causal):
    f = 4 * batch * seqlen ** 2 * nheads * headdim // (2 if causal else 1)
    return f


def compute_memory_per_layer(batch, seqlen, nheads, headdim, dtype_bytes):
    qkvo_bytes = 4 * batch * seqlen * nheads * headdim * dtype_bytes
    attn_matrix_bytes = batch * nheads * seqlen * seqlen * dtype_bytes
    standard_bytes = qkvo_bytes + attn_matrix_bytes
    softmax_lse_bytes = batch * nheads * seqlen * 4
    flash_bytes = qkvo_bytes + softmax_lse_bytes
    return {"standard_bytes": standard_bytes, "flash_bytes": flash_bytes}


def compute_max_batch_flash(gpu_memory_gb, seqlen, nheads, headdim, dtype_bytes):
    gpu_memory_bytes = gpu_memory_gb * (1024 ** 3)
    per_sample = 4 * seqlen * nheads * headdim * dtype_bytes + nheads * seqlen * 4
    if per_sample == 0:
        return 0
    return gpu_memory_bytes // per_sample


def main():
    nodes = query_nodes("/app/cluster.db")
    workloads = parse_workloads("/app/workloads.csv")
    config = load_config("/app/cluster_config.toml")

    minutes_per_target = config["build"]["minutes_per_gencode_target"]

    report = {
        "nodes": {},
        "performance_analysis": {},
        "build_priority": [],
        "deployment_plan": {},
        "ranking": [],
    }

    node_avg_pp = {}
    build_time_data = []
    workload_candidates = {wl["name"]: [] for wl in workloads}

    # Compute per-workload memory savings (node-independent)
    for wl in workloads:
        mem = compute_memory_per_layer(
            wl["batch_size"], wl["seq_len"], wl["nheads"],
            wl["headdim"], wl["dtype_bytes"],
        )
        ratio = round(mem["standard_bytes"] / mem["flash_bytes"], 1)
        report["performance_analysis"][wl["name"]] = {
            "memory_savings_ratio": ratio,
        }

    # Rank workloads by memory savings descending
    impact = sorted(
        [wl["name"] for wl in workloads],
        key=lambda w: -report["performance_analysis"][w]["memory_savings_ratio"],
    )
    report["performance_analysis"]["flash_attention_impact"] = impact

    for node in nodes:
        node_name = node["name"]
        cc = (node["compute_cap_major"], node["compute_cap_minor"])
        gpu_mem = node["gpu_memory_gb"]
        cuda_ver = node["cuda_version"]
        cpu_cores = node["cpu_cores"]
        sys_mem = node["system_memory_gb"]
        nvcc_threads = node["nvcc_threads"]
        peak_tflops = node["peak_tflops_fp16"]
        cost_per_hour = node["cost_per_hour_usd"]

        # Get target architectures from TOML config
        target_archs = config["nodes"][node_name]["target_architectures"]

        gencode_flags = generate_gencodes(cuda_ver, target_archs)
        max_jobs = compute_max_build_jobs(cpu_cores, sys_mem, nvcc_threads)
        num_gencode_targets = len(gencode_flags) // 2
        est_build_time = round(num_gencode_targets * minutes_per_target / max_jobs, 1)
        build_time_data.append((est_build_time, node_name))

        workloads_result = {}
        pp_values = []

        for wl in workloads:
            wl_name = wl["name"]
            batch = wl["batch_size"]
            seqlen = wl["seq_len"]
            nheads = wl["nheads"]
            headdim = wl["headdim"]
            causal = wl["causal"]
            dtype_bytes = wl["dtype_bytes"]
            dropout = wl["dropout"]

            block_n = get_block_size_n(cc, headdim, dropout, causal)
            fwd_flops = compute_fwd_flops(batch, seqlen, headdim, nheads, causal)
            mem = compute_memory_per_layer(batch, seqlen, nheads, headdim, dtype_bytes)
            max_batch = compute_max_batch_flash(gpu_mem, seqlen, nheads, headdim, dtype_bytes)
            feasible = batch <= max_batch
            dp_gpus = 1 if feasible else math.ceil(batch / max_batch)
            pp = round(peak_tflops / (cost_per_hour * dp_gpus), 2)
            pp_values.append(pp)

            workloads_result[wl_name] = {
                "kernel_block_n": block_n,
                "fwd_flops": fwd_flops,
                "memory_per_layer": mem,
                "max_batch_flash": max_batch,
                "feasible": feasible,
                "data_parallel_gpus": dp_gpus,
                "price_performance": pp,
            }

            workload_candidates[wl_name].append({
                "node": node_name,
                "feasible": feasible,
                "dp_gpus": dp_gpus,
                "pp": pp,
            })

        report["nodes"][node_name] = {
            "gencode_flags": gencode_flags,
            "max_build_jobs": max_jobs,
            "estimated_build_time_minutes": est_build_time,
            "workloads": workloads_result,
        }
        node_avg_pp[node_name] = round(sum(pp_values) / len(pp_values), 2)

    # Build priority: ascending build time, alphabetical ties
    build_time_data.sort(key=lambda x: (x[0], x[1]))
    report["build_priority"] = [x[1] for x in build_time_data]

    # Deployment plan: best node per workload
    for wl_name, candidates in workload_candidates.items():
        feasible_cands = [c for c in candidates if c["feasible"]]
        if feasible_cands:
            feasible_cands.sort(key=lambda c: (-c["pp"], c["node"]))
            best = feasible_cands[0]
        else:
            candidates.sort(key=lambda c: (c["dp_gpus"], -c["pp"], c["node"]))
            best = candidates[0]

        report["deployment_plan"][wl_name] = {
            "assigned_node": best["node"],
            "gpus_required": best["dp_gpus"],
            "price_performance": best["pp"],
        }

    # Ranking: average price_performance descending, alphabetical ties
    report["ranking"] = sorted(
        node_avg_pp.keys(),
        key=lambda n: (-node_avg_pp[n], n),
    )

    with open("/app/report.json", "w") as f:
        json.dump(report, f, indent=2)

    print("Report written to /app/report.json")


if __name__ == "__main__":
    main()
