#!/usr/bin/env python3

"""
Analyzes a KTransformers deployment environment and produces an audit report.
Reads hardware specs, model config, VRAM profile, activation traces, and
launch config to compute hardware capabilities, memory budgets, configuration
issues, and optimal expert placement.
"""

import json
import re


def parse_cpuinfo(path):
    with open(path) as f:
        content = f.read()

    # CPU model
    m = re.search(r"model name\s*:\s*(.+)", content)
    cpu_model = m.group(1).strip() if m else "unknown"

    # Sockets (distinct physical id values)
    physical_ids = set(re.findall(r"physical id\s*:\s*(\d+)", content))
    num_sockets = len(physical_ids)

    # Cores per socket
    m = re.search(r"cpu cores\s*:\s*(\d+)", content)
    cores_per_socket = int(m.group(1)) if m else 1

    total_physical_cores = num_sockets * cores_per_socket

    # CPU flags (take from first processor entry)
    m = re.search(r"flags\s*:\s*(.+)", content)
    flags = set(m.group(1).split()) if m else set()

    has_amx = bool({"amx_tile", "amx_int8", "amx_bf16"} & flags)
    has_avx512 = "avx512f" in flags
    has_avx512_vnni = bool({"avx512_vnni", "avx512vnni"} & flags)
    has_avx512_bf16 = bool({"avx512_bf16", "avx512bf16"} & flags)
    has_avx512_vbmi = bool({"avx512_vbmi", "avx512vbmi"} & flags)

    # Determine optimal kernel variant (priority: AMX > BF16 > VBMI > VNNI > AVX512 > AVX2)
    if has_amx:
        optimal_variant = "amx"
    elif has_avx512_bf16:
        optimal_variant = "avx512_bf16"
    elif has_avx512_vbmi:
        optimal_variant = "avx512_vbmi"
    elif has_avx512_vnni:
        optimal_variant = "avx512_vnni"
    elif has_avx512:
        optimal_variant = "avx512"
    else:
        optimal_variant = "avx2"

    return {
        "cpu_model": cpu_model,
        "physical_cores_per_socket": cores_per_socket,
        "num_sockets": num_sockets,
        "total_physical_cores": total_physical_cores,
        "has_amx": has_amx,
        "has_avx512": has_avx512,
        "has_avx512_vnni": has_avx512_vnni,
        "has_avx512_bf16": has_avx512_bf16,
        "has_avx512_vbmi": has_avx512_vbmi,
        "optimal_kernel_variant": optimal_variant,
    }


def compute_memory_analysis(model_config, vram_profile, gpu_inventory):
    H = model_config["hidden_size"]
    I = model_config["moe_intermediate_size"]
    q = model_config["quantization_config"]
    bits = q["bits"]
    gs = q["group_size"]
    sd = q["scale_dtype"]
    scale_bytes = 2 if sd in ("bfloat16", "float16") else 4

    expert_param_count = 3 * H * I
    weight_bytes = expert_param_count * bits // 8
    scale_total = (expert_param_count // gs) * scale_bytes
    expert_memory_bytes = weight_bytes + scale_total

    non_expert_vram = sum(vram_profile["components"].values())
    gpu_vram = gpu_inventory["gpus"][0]["vram_bytes"]
    available = gpu_vram - non_expert_vram
    max_gpu_experts = available // expert_memory_bytes

    return {
        "expert_param_count": expert_param_count,
        "expert_memory_bytes": expert_memory_bytes,
        "non_expert_vram_bytes": non_expert_vram,
        "available_expert_vram_bytes": available,
        "max_gpu_experts": max_gpu_experts,
    }


def find_config_issues(launch_config, model_config, hw_caps, numa_topo, mem_analysis):
    issues = []
    num_layers = model_config["num_moe_layers"]
    total_physical = hw_caps["total_physical_cores"]
    numa_count = len(numa_topo["nodes"])

    # 1. kt_method vs model quantization
    model_method = model_config["quantization_config"]["quant_method"].upper()
    if launch_config["kt_method"].upper() != model_method:
        issues.append({
            "parameter": "kt_method",
            "current_value": launch_config["kt_method"],
            "problem": (
                f"Model uses {model_method} quantization but kt_method is set to "
                f"{launch_config['kt_method']}. This causes precision mismatch."
            ),
        })

    # 2. kt_cpuinfer exceeds physical cores
    if launch_config["kt_cpuinfer"] > total_physical:
        issues.append({
            "parameter": "kt_cpuinfer",
            "current_value": launch_config["kt_cpuinfer"],
            "problem": (
                f"Set to {launch_config['kt_cpuinfer']} but system has only "
                f"{total_physical} physical cores. Using hyperthreads for "
                f"compute-bound inference causes contention and reduces throughput."
            ),
        })

    # 3. kt_threadpool_count doesn't match NUMA
    if launch_config["kt_threadpool_count"] != numa_count:
        issues.append({
            "parameter": "kt_threadpool_count",
            "current_value": launch_config["kt_threadpool_count"],
            "problem": (
                f"Set to {launch_config['kt_threadpool_count']} but system has "
                f"{numa_count} NUMA nodes. Should match NUMA node count to avoid "
                f"cross-node memory traffic."
            ),
        })

    # 4. kt_num_gpu_experts causes OOM
    total_expert_slots = launch_config["kt_num_gpu_experts"] * num_layers
    max_experts = mem_analysis["max_gpu_experts"]
    if total_expert_slots > max_experts:
        expert_mem = mem_analysis["expert_memory_bytes"]
        required = total_expert_slots * expert_mem
        available = mem_analysis["available_expert_vram_bytes"]
        issues.append({
            "parameter": "kt_num_gpu_experts",
            "current_value": launch_config["kt_num_gpu_experts"],
            "problem": (
                f"Requests {launch_config['kt_num_gpu_experts']} experts/layer x "
                f"{num_layers} layers = {total_expert_slots} total, requiring "
                f"{required} bytes, but only {available} bytes available for experts "
                f"(max {max_experts}). This causes CUDA OOM."
            ),
        })

    # 5. chunked_prefill_size > max_total_tokens
    if launch_config["chunked_prefill_size"] > launch_config["max_total_tokens"]:
        issues.append({
            "parameter": "chunked_prefill_size",
            "current_value": launch_config["chunked_prefill_size"],
            "problem": (
                f"Set to {launch_config['chunked_prefill_size']} which exceeds "
                f"max_total_tokens ({launch_config['max_total_tokens']}). "
                f"Prefill batch cannot exceed KV cache budget."
            ),
        })

    # 6. max_running_requests * max_new_tokens > max_total_tokens
    product = launch_config["max_running_requests"] * launch_config["max_new_tokens"]
    if product > launch_config["max_total_tokens"]:
        issues.append({
            "parameter": "max_running_requests",
            "current_value": launch_config["max_running_requests"],
            "problem": (
                f"max_running_requests ({launch_config['max_running_requests']}) x "
                f"max_new_tokens ({launch_config['max_new_tokens']}) = {product} "
                f"exceeds max_total_tokens ({launch_config['max_total_tokens']}). "
                f"Concurrent requests will exhaust KV cache."
            ),
        })

    return issues


def compute_optimal_placement(activation_profile, budget):
    counts = activation_profile["layer_expert_counts"]
    num_layers = len(counts)

    # Rank all experts globally by activation count (desc), tiebreak by layer then expert
    ranked = []
    for li, layer in enumerate(counts):
        for ei, count in enumerate(layer):
            ranked.append((-count, li, ei))
    ranked.sort()

    # Select top-K
    placement = {}
    for _, li, ei in ranked[:budget]:
        key = str(li)
        if key not in placement:
            placement[key] = []
        placement[key].append(ei)

    # Sort indices within each layer
    for key in placement:
        placement[key].sort()

    # Ensure all layers are present
    for li in range(num_layers):
        if str(li) not in placement:
            placement[str(li)] = []

    # Compute hit rate
    total = sum(sum(layer) for layer in counts)
    gpu_hits = 0
    for ls, experts in placement.items():
        for ei in experts:
            gpu_hits += counts[int(ls)][ei]
    hit_rate = gpu_hits / total

    total_experts = sum(len(layer) for layer in counts)

    return {
        "total_experts": total_experts,
        "gpu_expert_budget": budget,
        "optimal_placement": placement,
        "optimal_hit_rate": round(hit_rate, 6),
    }


def main():
    # Load all data
    with open("/app/model/config.json") as f:
        model_config = json.load(f)
    with open("/app/model/activation_profile.json") as f:
        activation_profile = json.load(f)
    with open("/app/model/vram_profile.json") as f:
        vram_profile = json.load(f)
    with open("/app/system/gpu_inventory.json") as f:
        gpu_inventory = json.load(f)
    with open("/app/system/numa_topology.json") as f:
        numa_topology = json.load(f)
    with open("/app/deploy/launch_config.json") as f:
        launch_config = json.load(f)

    # 1. Hardware capabilities
    hw_caps = parse_cpuinfo("/app/system/cpuinfo")
    hw_caps["numa_node_count"] = len(numa_topology["nodes"])
    hw_caps["memory_per_numa_node_mb"] = numa_topology["nodes"][0]["memory_mb"]
    hw_caps["total_system_memory_mb"] = sum(n["memory_mb"] for n in numa_topology["nodes"])
    hw_caps["gpu_count"] = len(gpu_inventory["gpus"])
    hw_caps["gpu_vram_bytes"] = gpu_inventory["gpus"][0]["vram_bytes"]

    # 2. Memory analysis
    mem_analysis = compute_memory_analysis(model_config, vram_profile, gpu_inventory)

    # 3. Configuration issues
    config_issues = find_config_issues(
        launch_config, model_config, hw_caps, numa_topology, mem_analysis
    )

    # 4. Expert placement
    expert_placement = compute_optimal_placement(
        activation_profile, mem_analysis["max_gpu_experts"]
    )

    # Build report
    report = {
        "hardware_capabilities": hw_caps,
        "memory_analysis": mem_analysis,
        "configuration_issues": config_issues,
        "expert_placement": expert_placement,
    }

    with open("/app/audit_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print("Audit report written to /app/audit_report.json")


if __name__ == "__main__":
    main()
