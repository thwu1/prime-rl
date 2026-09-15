#!/usr/bin/env python3
"""ERNIEKit parallelism planner and memory estimator."""

import argparse
import json
import math
import sys

import yaml

MODELS_PATH = "/app/models.json"


def load_models():
    with open(MODELS_PATH) as f:
        return json.load(f)


def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f)


def is_power_of_two(n):
    return n > 0 and (n & (n - 1)) == 0


def estimate_memory(cfg, model_spec):
    """Estimate per-GPU memory in GB. Returns dict with breakdown."""
    tp = cfg.get("tensor_parallel_degree", 1)
    pp = cfg.get("pipeline_parallel_degree", 1)
    sp = cfg.get("sharding_parallel_degree", 1)
    sharding = cfg.get("sharding", "stage1")
    compute_type = cfg.get("compute_type", "bf16")
    seq_len = cfg.get("max_seq_len", 8192)
    batch_size = cfg.get("batch_size", 1)
    seq_parallel = cfg.get("sequence_parallel", False)
    recompute = cfg.get("recompute", False)
    offload_optim = cfg.get("offload_optim", False)
    tw_offload = cfg.get("tensorwise_offload_optimizer", False)
    low_prec_moment = cfg.get("use_lowprecision_moment", False)

    total_params = model_spec["total_params_billions"] * 1e9
    num_layers = model_spec["num_layers"]
    hidden_dim = model_spec["hidden_dim"]

    params_per_gpu = total_params / (tp * pp)

    # Parameter storage
    param_bytes = 1 if compute_type == "fp8" else 2
    p_mem = params_per_gpu * param_bytes / 1e9

    # Gradient storage (always bf16)
    g_mem_raw = params_per_gpu * 2 / 1e9

    # Optimizer storage
    if tw_offload or offload_optim:
        optim_bytes = 0
    elif low_prec_moment:
        optim_bytes = 8  # master(4) + m1(2) + m2(2)
    else:
        optim_bytes = 12  # master(4) + m1(4) + m2(4)
    o_mem_raw = params_per_gpu * optim_bytes / 1e9

    # Apply sharding
    if sharding == "stage1":
        o_mem = o_mem_raw / sp
        g_mem = g_mem_raw
    elif sharding == "stage2":
        o_mem = o_mem_raw / sp
        g_mem = g_mem_raw / sp
    elif sharding == "stage3":
        o_mem = o_mem_raw / sp
        g_mem = g_mem_raw / sp
        p_mem = p_mem / sp
    else:
        o_mem = o_mem_raw / sp
        g_mem = g_mem_raw

    # Activation memory
    layers_per_stage = math.ceil(num_layers / pp)
    act_bytes_per_layer = seq_len * batch_size * hidden_dim * 24

    if seq_parallel and tp > 1:
        act_bytes_per_layer = act_bytes_per_layer / tp

    if recompute:
        a_mem = act_bytes_per_layer * 2 / 1e9
    else:
        a_mem = act_bytes_per_layer * layers_per_stage / 1e9

    total = p_mem + g_mem + o_mem + a_mem

    return {
        "param_memory_gb": p_mem,
        "grad_memory_gb": g_mem,
        "optim_memory_gb": o_mem,
        "activation_memory_gb": a_mem,
        "total_memory_gb": total,
    }


def make_pp_seg(num_layers, pp):
    """Generate uniform pp_seg_method."""
    step = math.ceil(num_layers / pp)
    seg = []
    for i in range(pp + 1):
        seg.append(min(i * step, num_layers))
    return seg


def plan_config(model_spec, num_gpus, gpu_mem_gb, seq_len, batch_size, compute_type):
    """Find optimal parallelism config that fits in GPU memory."""
    num_layers = model_spec["num_layers"]
    hidden_dim = model_spec["hidden_dim"]
    is_moe = model_spec.get("is_moe", False)

    candidates = []

    # Enumerate all valid (TP, PP, s)
    tp = 1
    while tp <= num_gpus:
        if not is_power_of_two(tp):
            tp += 1
            continue
        for pp in range(1, num_gpus // tp + 1):
            for s in range(1, num_gpus // (tp * pp) + 1):
                product = tp * pp * s
                if product > num_gpus:
                    break
                if num_gpus % product != 0:
                    continue
                candidates.append((tp, pp, s))
        tp *= 2

    def build_cfg(tp, pp, s, offload):
        cfg = {
            "tensor_parallel_degree": tp,
            "pipeline_parallel_degree": pp,
            "sharding_parallel_degree": s,
            "sharding": "stage1",
            "sequence_parallel": tp > 1,
            "recompute": True,
            "compute_type": compute_type,
            "max_seq_len": seq_len,
            "batch_size": batch_size,
            "fp16_opt_level": "O2",
        }
        if compute_type == "fp8":
            cfg["apply_hadamard"] = True
            cfg["use_lowprecision_moment"] = True
            cfg["tensorwise_offload_optimizer"] = True
        else:
            cfg["offload_optim"] = offload
        return cfg

    def cost(tp, pp, s):
        return 3 * tp + 2 * pp + s

    # First pass: try without offload (for bf16; fp8 always offloads)
    feasible = []
    for tp, pp, s in candidates:
        offload = compute_type == "fp8"  # fp8 always offloads
        cfg = build_cfg(tp, pp, s, offload=offload)
        mem = estimate_memory(cfg, model_spec)
        if mem["total_memory_gb"] <= gpu_mem_gb:
            c = cost(tp, pp, s)
            feasible.append((c, tp, pp, s, False))

    # Second pass (bf16 only): try with offload if nothing fits
    if not feasible and compute_type == "bf16":
        for tp, pp, s in candidates:
            cfg = build_cfg(tp, pp, s, offload=True)
            mem = estimate_memory(cfg, model_spec)
            if mem["total_memory_gb"] <= gpu_mem_gb:
                c = cost(tp, pp, s)
                feasible.append((c, tp, pp, s, True))

    if not feasible:
        print("ERROR: No feasible parallelism configuration found.", file=sys.stderr)
        sys.exit(1)

    # Sort by cost, then (TP, PP, s) lexicographically
    feasible.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
    _, best_tp, best_pp, best_s, offload = feasible[0]

    # Build final config
    final = {
        "model_name_or_path": model_spec["model_name_or_path"],
        "fine_tuning": "Full",
        "stage": "SFT",
        "train_dataset_type": "erniekit",
        "eval_dataset_type": "erniekit",
        "train_dataset_path": "./data/sft-train.jsonl",
        "eval_dataset_path": "./data/sft-eval.jsonl",
        "max_seq_len": seq_len,
        "batch_size": batch_size,
        "gradient_accumulation_steps": 8,
        "learning_rate": 1.0e-5,
        "lr_scheduler_type": "cosine",
        "warmup_steps": 20,
        "weight_decay": 0.1,
        "optim": "adamw",
        "tensor_parallel_degree": best_tp,
        "pipeline_parallel_degree": best_pp,
        "sharding_parallel_degree": best_s,
        "sharding": "stage1",
        "sequence_parallel": best_tp > 1,
        "recompute": True,
        "compute_type": compute_type,
        "fp16_opt_level": "O2",
        "amp_custom_white_list": ["lookup_table", "flash_attn", "matmul"],
        "amp_custom_black_list": [
            "reduce_sum",
            "softmax_with_cross_entropy",
            "elementwise_div",
        ],
    }

    if compute_type == "fp8":
        final["apply_hadamard"] = True
        final["use_lowprecision_moment"] = True
        final["tensorwise_offload_optimizer"] = True
    elif offload:
        final["offload_optim"] = True

    if best_pp > 1:
        final["pp_seg_method"] = make_pp_seg(num_layers, best_pp)

    if is_moe:
        final["moe_group"] = "mp"

    return final


def main():
    parser = argparse.ArgumentParser(description="ERNIEKit parallelism planner")
    subparsers = parser.add_subparsers(dest="command")

    est_p = subparsers.add_parser("estimate")
    est_p.add_argument("config", help="Path to YAML config")
    est_p.add_argument("--model", required=True)

    plan_p = subparsers.add_parser("plan")
    plan_p.add_argument("--model", required=True)
    plan_p.add_argument("--num-gpus", type=int, required=True)
    plan_p.add_argument("--gpu-mem-gb", type=float, required=True)
    plan_p.add_argument("--seq-len", type=int, required=True)
    plan_p.add_argument("--batch-size", type=int, required=True)
    plan_p.add_argument("--compute-type", required=True, choices=["fp8", "bf16"])
    plan_p.add_argument("--output", required=True)

    args = parser.parse_args()
    models = load_models()
    model_spec = models[args.model]

    if args.command == "estimate":
        cfg = load_config(args.config)
        result = estimate_memory(cfg, model_spec)
        print(json.dumps(result, indent=2))

    elif args.command == "plan":
        cfg = plan_config(
            model_spec,
            args.num_gpus,
            args.gpu_mem_gb,
            args.seq_len,
            args.batch_size,
            args.compute_type,
        )
        with open(args.output, "w") as f:
            yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)


if __name__ == "__main__":
    main()
