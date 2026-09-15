#!/usr/bin/env python3
"""ERNIEKit training config validator — validates and fixes YAML configs."""

import argparse
import json
import math
import sys

import yaml

MODELS_PATH = "/app/models.json"

VALID_SHARDING = {"stage1", "stage2", "stage3"}
VALID_LR_SCHEDULERS = {"cosine", "linear", "constant", "constant_with_warmup"}
VALID_FP16_OPT = {"O1", "O2"}
VALID_OPTIMIZERS = {"adamw", "adamw_custom", "sgd"}


def load_models():
    with open(MODELS_PATH) as f:
        return json.load(f)


def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f)


def is_power_of_two(n):
    return n > 0 and (n & (n - 1)) == 0


def validate(cfg, model_spec, num_gpus):
    """Return list of {rule, message} dicts."""
    violations = []

    tp = cfg.get("tensor_parallel_degree", 1)
    pp = cfg.get("pipeline_parallel_degree", 1)
    sp = cfg.get("sharding_parallel_degree", 1)
    compute_type = cfg.get("compute_type", "bf16")
    sharding = cfg.get("sharding", "stage1")
    num_layers = model_spec["num_layers"]

    # TP_POWER_OF_TWO
    if not is_power_of_two(tp):
        violations.append({
            "rule": "TP_POWER_OF_TWO",
            "message": f"tensor_parallel_degree={tp} is not a power of 2",
        })

    # PP_POSITIVE
    if not isinstance(pp, int) or pp < 1:
        violations.append({
            "rule": "PP_POSITIVE",
            "message": f"pipeline_parallel_degree={pp} must be >= 1",
        })

    # PARALLEL_PRODUCT
    product = tp * max(pp, 1) * sp
    if product > num_gpus or (num_gpus % product != 0):
        violations.append({
            "rule": "PARALLEL_PRODUCT",
            "message": (
                f"TP({tp}) * PP({pp}) * sharding({sp}) = {product} "
                f"does not evenly divide num_gpus={num_gpus}"
            ),
        })

    # PP_SEG_METHOD
    if isinstance(pp, int) and pp > 1:
        seg = cfg.get("pp_seg_method")
        if seg is None:
            violations.append({
                "rule": "PP_SEG_METHOD",
                "message": "pp_seg_method is required when pipeline_parallel_degree > 1",
            })
        elif not isinstance(seg, list):
            violations.append({
                "rule": "PP_SEG_METHOD",
                "message": "pp_seg_method must be a list",
            })
        else:
            expected_len = pp + 1
            ok = True
            msgs = []
            if len(seg) != expected_len:
                msgs.append(
                    f"pp_seg_method has {len(seg)} elements, expected {expected_len}"
                )
                ok = False
            if ok and seg[0] != 0:
                msgs.append(f"pp_seg_method first element must be 0, got {seg[0]}")
                ok = False
            if ok and seg[-1] != num_layers:
                msgs.append(
                    f"pp_seg_method last element must be {num_layers}, got {seg[-1]}"
                )
                ok = False
            if ok:
                for i in range(1, len(seg)):
                    if seg[i] <= seg[i - 1]:
                        msgs.append("pp_seg_method must be strictly increasing")
                        ok = False
                        break
            if not ok:
                violations.append({
                    "rule": "PP_SEG_METHOD",
                    "message": "; ".join(msgs),
                })

    # FP8_HADAMARD
    if compute_type == "fp8":
        if cfg.get("apply_hadamard") is not True:
            violations.append({
                "rule": "FP8_HADAMARD",
                "message": "apply_hadamard must be True when compute_type is fp8",
            })

    # FP8_OPTIM
    if compute_type == "fp8":
        missing = []
        if cfg.get("tensorwise_offload_optimizer") is not True:
            missing.append("tensorwise_offload_optimizer")
        if cfg.get("use_lowprecision_moment") is not True:
            missing.append("use_lowprecision_moment")
        if missing:
            violations.append({
                "rule": "FP8_OPTIM",
                "message": (
                    f"For fp8, {', '.join(missing)} must be True"
                ),
            })

    # AMP_DISJOINT
    white = set(cfg.get("amp_custom_white_list") or [])
    black = set(cfg.get("amp_custom_black_list") or [])
    overlap = white & black
    if overlap:
        violations.append({
            "rule": "AMP_DISJOINT",
            "message": (
                f"amp_custom_white_list and black_list overlap: {sorted(overlap)}"
            ),
        })

    # SHARDING_VALID
    if sharding not in VALID_SHARDING:
        violations.append({
            "rule": "SHARDING_VALID",
            "message": f"sharding='{sharding}' must be one of {sorted(VALID_SHARDING)}",
        })

    # MOE_GROUP
    if model_spec.get("is_moe"):
        moe_group = cfg.get("moe_group")
        if not moe_group:
            violations.append({
                "rule": "MOE_GROUP",
                "message": "moe_group is required for MoE models",
            })

    # LR_SCHEDULER
    lr = cfg.get("lr_scheduler_type")
    if lr is not None and lr not in VALID_LR_SCHEDULERS:
        violations.append({
            "rule": "LR_SCHEDULER",
            "message": (
                f"lr_scheduler_type='{lr}' must be one of "
                f"{sorted(VALID_LR_SCHEDULERS)}"
            ),
        })

    # FP16_OPT_LEVEL
    fp16 = cfg.get("fp16_opt_level")
    if fp16 is not None and fp16 not in VALID_FP16_OPT:
        violations.append({
            "rule": "FP16_OPT_LEVEL",
            "message": f"fp16_opt_level='{fp16}' must be one of {sorted(VALID_FP16_OPT)}",
        })

    # BATCH_POSITIVE
    bs = cfg.get("batch_size")
    ga = cfg.get("gradient_accumulation_steps")
    batch_msgs = []
    if bs is not None and (not isinstance(bs, int) or bs <= 0):
        batch_msgs.append(f"batch_size={bs} must be > 0")
    if ga is not None and (not isinstance(ga, int) or ga <= 0):
        batch_msgs.append(f"gradient_accumulation_steps={ga} must be > 0")
    if batch_msgs:
        violations.append({
            "rule": "BATCH_POSITIVE",
            "message": "; ".join(batch_msgs),
        })

    # OPTIMIZER_VALID
    optim = cfg.get("optim")
    if optim is not None and optim not in VALID_OPTIMIZERS:
        violations.append({
            "rule": "OPTIMIZER_VALID",
            "message": (
                f"optim='{optim}' must be one of {sorted(VALID_OPTIMIZERS)}"
            ),
        })

    return violations


def fix_config(cfg, model_spec, num_gpus):
    """Return a copy of cfg with all violations fixed."""
    cfg = dict(cfg)  # shallow copy — deep copy lists later as needed
    num_layers = model_spec["num_layers"]

    # --- Simple field fixes ---

    # SHARDING_VALID
    if cfg.get("sharding") not in VALID_SHARDING:
        cfg["sharding"] = "stage1"

    # FP16_OPT_LEVEL
    if cfg.get("fp16_opt_level") not in VALID_FP16_OPT:
        cfg["fp16_opt_level"] = "O2"

    # LR_SCHEDULER
    if cfg.get("lr_scheduler_type") not in VALID_LR_SCHEDULERS:
        cfg["lr_scheduler_type"] = "cosine"

    # OPTIMIZER_VALID
    if cfg.get("optim") is not None and cfg["optim"] not in VALID_OPTIMIZERS:
        cfg["optim"] = "adamw"

    # BATCH_POSITIVE
    if cfg.get("batch_size") is not None and (
        not isinstance(cfg["batch_size"], int) or cfg["batch_size"] <= 0
    ):
        cfg["batch_size"] = 1
    if cfg.get("gradient_accumulation_steps") is not None and (
        not isinstance(cfg["gradient_accumulation_steps"], int)
        or cfg["gradient_accumulation_steps"] <= 0
    ):
        cfg["gradient_accumulation_steps"] = 1

    # MOE_GROUP
    if model_spec.get("is_moe") and not cfg.get("moe_group"):
        cfg["moe_group"] = "mp"

    # FP8_HADAMARD
    if cfg.get("compute_type") == "fp8":
        cfg["apply_hadamard"] = True

    # FP8_OPTIM
    if cfg.get("compute_type") == "fp8":
        cfg["tensorwise_offload_optimizer"] = True
        cfg["use_lowprecision_moment"] = True

    # --- TP_POWER_OF_TWO ---
    tp = cfg.get("tensor_parallel_degree", 1)
    if not is_power_of_two(tp):
        # Round up to next power of 2
        tp = 1
        while tp < cfg.get("tensor_parallel_degree", 1):
            tp *= 2
        cfg["tensor_parallel_degree"] = tp

    # --- PP_POSITIVE ---
    pp = cfg.get("pipeline_parallel_degree", 1)
    if not isinstance(pp, int) or pp < 1:
        cfg["pipeline_parallel_degree"] = 1
        pp = 1

    # --- PARALLEL_PRODUCT ---
    tp = cfg.get("tensor_parallel_degree", 1)
    pp = cfg.get("pipeline_parallel_degree", 1)
    sp = cfg.get("sharding_parallel_degree", 1)

    while tp * pp * sp > num_gpus or num_gpus % (tp * pp * sp) != 0:
        if sp > 1:
            sp = 1
            continue
        if pp > 1:
            pp -= 1
            continue
        if tp > 1:
            tp = tp // 2
            continue
        break

    cfg["tensor_parallel_degree"] = tp
    cfg["pipeline_parallel_degree"] = pp
    cfg["sharding_parallel_degree"] = sp

    # --- PP_SEG_METHOD ---
    pp = cfg["pipeline_parallel_degree"]
    if pp > 1:
        step = math.ceil(num_layers / pp)
        seg = []
        for i in range(pp + 1):
            seg.append(min(i * step, num_layers))
        cfg["pp_seg_method"] = seg
    elif pp == 1:
        # Remove pp_seg_method if PP=1
        cfg.pop("pp_seg_method", None)

    # --- AMP_DISJOINT ---
    white = list(cfg.get("amp_custom_white_list") or [])
    black = set(cfg.get("amp_custom_black_list") or [])
    overlap = set(white) & black
    if overlap:
        cfg["amp_custom_white_list"] = [op for op in white if op not in overlap]

    return cfg


def main():
    parser = argparse.ArgumentParser(description="ERNIEKit config validator")
    subparsers = parser.add_subparsers(dest="command")

    val_p = subparsers.add_parser("validate")
    val_p.add_argument("config", help="Path to YAML config")
    val_p.add_argument("--model", required=True)
    val_p.add_argument("--num-gpus", type=int, required=True)

    fix_p = subparsers.add_parser("fix")
    fix_p.add_argument("config", help="Path to YAML config")
    fix_p.add_argument("--model", required=True)
    fix_p.add_argument("--num-gpus", type=int, required=True)
    fix_p.add_argument("--output", required=True)

    args = parser.parse_args()
    models = load_models()
    model_spec = models[args.model]
    cfg = load_config(args.config)

    if args.command == "validate":
        violations = validate(cfg, model_spec, args.num_gpus)
        result = {
            "config_file": args.config,
            "model": args.model,
            "num_gpus": args.num_gpus,
            "violations": violations,
            "num_violations": len(violations),
        }
        print(json.dumps(result, indent=2))

    elif args.command == "fix":
        fixed = fix_config(cfg, model_spec, args.num_gpus)
        with open(args.output, "w") as f:
            yaml.dump(fixed, f, default_flow_style=False, sort_keys=False)


if __name__ == "__main__":
    main()
