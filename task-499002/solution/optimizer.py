#!/usr/bin/env python3
"""
MoE Expert GPU Placement Optimizer

Reads model configuration, expert activation statistics, and hardware constraints
to compute optimal GPU expert placement masks for CPU/GPU heterogeneous MoE
inference systems (e.g., KTransformers).

Implements four placement strategies: uniform, frequency, front_loading, random.
"""

import json
import math
import random as rng


def load_json(path):
    with open(path) as f:
        return json.load(f)


def compute_expert_memory_bytes(model_config):
    """
    Compute per-expert GPU memory in bytes for INT4 quantization.

    Each expert has 3 projection matrices (gate, up, down):
      gate_proj: [moe_intermediate_size, hidden_size]
      up_proj:   [moe_intermediate_size, hidden_size]
      down_proj: [hidden_size, moe_intermediate_size]

    Total parameters = 3 * moe_intermediate_size * hidden_size

    INT4 memory per expert:
      weight_bytes = total_params * bits / 8
      scale_bytes  = (total_params / group_size) * scale_dtype_bytes
      total        = weight_bytes + scale_bytes
    """
    I = model_config["moe_intermediate_size"]
    H = model_config["hidden_size"]
    qcfg = model_config["quantization"]
    bits = qcfg["bits"]
    group_size = qcfg["group_size"]
    scale_dtype_bytes = qcfg["scale_dtype_bytes"]

    total_params = 3 * I * H
    weight_bytes = total_params * bits // 8
    num_groups = total_params // group_size
    scale_bytes = num_groups * scale_dtype_bytes

    return weight_bytes + scale_bytes


def compute_gpu_hit_rate(placement, layer_expert_counts):
    """
    Compute fraction of expert activations served by GPU.

    GPU hit rate = sum(activation_count for GPU-placed experts) / total_activations
    """
    total = sum(sum(row) for row in layer_expert_counts)
    if total == 0:
        return 0.0

    gpu_sum = 0
    for layer_str, experts in placement.items():
        layer_idx = int(layer_str)
        for expert_idx in experts:
            gpu_sum += layer_expert_counts[layer_idx][expert_idx]

    return round(gpu_sum / total, 6)


def strategy_uniform(num_layers, num_experts, max_gpu_experts):
    """
    Distribute GPU experts evenly across layers.
    Extras go to earlier layers (layer 0 first).
    Within each layer, select experts [0, 1, ..., n-1] by index.
    """
    base = max_gpu_experts // num_layers
    remainder = max_gpu_experts % num_layers

    per_layer_counts = [
        base + (1 if i < remainder else 0) for i in range(num_layers)
    ]

    placement = {}
    for i in range(num_layers):
        placement[str(i)] = list(range(per_layer_counts[i]))

    return per_layer_counts, placement


def strategy_frequency(num_layers, num_experts, max_gpu_experts, layer_expert_counts):
    """
    Select top max_gpu_experts experts globally by activation count.
    Tiebreak: prefer lower layer index, then lower expert index.
    """
    # Build (negative_count, layer, expert) for ascending sort
    all_experts = []
    for layer_idx in range(num_layers):
        for expert_idx in range(num_experts):
            count = layer_expert_counts[layer_idx][expert_idx]
            all_experts.append((-count, layer_idx, expert_idx))

    all_experts.sort()

    # Select top K
    selected = all_experts[:max_gpu_experts]

    # Build result
    placement = {str(i): [] for i in range(num_layers)}
    per_layer_counts = [0] * num_layers

    for _, layer_idx, expert_idx in selected:
        placement[str(layer_idx)].append(expert_idx)
        per_layer_counts[layer_idx] += 1

    # Sort expert indices within each layer
    for key in placement:
        placement[key].sort()

    return per_layer_counts, placement


def strategy_front_loading(num_layers, num_experts, max_gpu_experts):
    """
    Fill layers sequentially from layer 0.
    Each layer gets all its experts until budget is exhausted.
    Last filled layer may be partial.
    """
    per_layer_counts = [0] * num_layers
    remaining = max_gpu_experts

    for i in range(num_layers):
        alloc = min(num_experts, remaining)
        per_layer_counts[i] = alloc
        remaining -= alloc
        if remaining <= 0:
            break

    placement = {}
    for i in range(num_layers):
        if per_layer_counts[i] > 0:
            placement[str(i)] = list(range(per_layer_counts[i]))
        else:
            placement[str(i)] = []

    return per_layer_counts, placement


def strategy_random(num_layers, num_experts, max_gpu_experts):
    """
    Same per-layer distribution as uniform.
    Use random.seed(42) once, then random.sample per layer in ascending order.
    """
    base = max_gpu_experts // num_layers
    remainder = max_gpu_experts % num_layers

    per_layer_counts = [
        base + (1 if i < remainder else 0) for i in range(num_layers)
    ]

    rng.seed(42)
    placement = {}
    for i in range(num_layers):
        selected = rng.sample(range(num_experts), per_layer_counts[i])
        placement[str(i)] = sorted(selected)

    return per_layer_counts, placement


def main():
    model_config = load_json("/app/model_config.json")
    activation_stats = load_json("/app/activation_stats.json")
    hardware_config = load_json("/app/hardware_config.json")

    num_layers = model_config["num_moe_layers"]
    num_experts = model_config["num_experts_per_layer"]
    layer_expert_counts = activation_stats["layer_expert_counts"]

    # Step 1: Compute per-expert memory
    expert_memory = compute_expert_memory_bytes(model_config)

    # Step 2: Compute available VRAM budget
    available = hardware_config["gpu_vram_bytes"] - hardware_config["non_expert_vram_bytes"]

    # Step 3: Max GPU experts
    max_gpu_experts = available // expert_memory
    total_experts = num_layers * num_experts
    max_gpu_experts = min(max_gpu_experts, total_experts)

    # Step 4: Run all strategies
    result = {
        "expert_memory_bytes": expert_memory,
        "available_budget_bytes": available,
        "max_total_gpu_experts": max_gpu_experts,
        "strategies": {},
    }

    strategy_fns = {
        "uniform": lambda: strategy_uniform(num_layers, num_experts, max_gpu_experts),
        "frequency": lambda: strategy_frequency(
            num_layers, num_experts, max_gpu_experts, layer_expert_counts
        ),
        "front_loading": lambda: strategy_front_loading(
            num_layers, num_experts, max_gpu_experts
        ),
        "random": lambda: strategy_random(num_layers, num_experts, max_gpu_experts),
    }

    for name, fn in strategy_fns.items():
        per_layer_counts, placement = fn()
        hit_rate = compute_gpu_hit_rate(placement, layer_expert_counts)
        result["strategies"][name] = {
            "per_layer_counts": per_layer_counts,
            "placement": placement,
            "gpu_hit_rate": hit_rate,
        }

    # Step 5: Write output
    with open("/app/placement_result.json", "w") as f:
        json.dump(result, f, indent=2)

    print(f"Expert memory: {expert_memory:,} bytes ({expert_memory / 1024 / 1024:.2f} MB)")
    print(f"Available VRAM: {available:,} bytes ({available / 1024 / 1024:.2f} MB)")
    print(f"Max GPU experts: {max_gpu_experts} / {total_experts}")
    print()
    for name, s in result["strategies"].items():
        print(f"  {name:20s}  hit_rate={s['gpu_hit_rate']:.6f}  counts={s['per_layer_counts']}")
    print()
    print("Results written to /app/placement_result.json")


if __name__ == "__main__":
    main()
