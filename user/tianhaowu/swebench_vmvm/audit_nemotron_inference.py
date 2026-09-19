#!/usr/bin/env python3

import argparse
import json
import tomllib
from pathlib import Path
from typing import Any

EXPECTED_MODEL = "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit the Nemotron Super inference configuration used by an eval.")
    parser.add_argument("config", type=Path)
    parser.add_argument("models", type=Path)
    parser.add_argument("startup_log", type=Path)
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def nested(config: dict[str, Any], *keys: str) -> Any:
    value: Any = config
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def main() -> None:
    args = parse_args()
    config = tomllib.loads(args.config.read_text())
    models = json.loads(args.models.read_text()).get("data") or []
    startup = args.startup_log.read_text(errors="replace")
    expected_config = {
        ("model", "name"): EXPECTED_MODEL,
        ("model", "max_model_len"): 262_144,
        ("model", "tool_call_parser"): "qwen3_coder",
        ("model", "reasoning_parser"): "nemotron_v3",
        ("parallel", "tp"): 8,
        ("vllm_extra", "served_model_name"): [EXPECTED_MODEL],
        ("vllm_extra", "language_model_only"): True,
        ("vllm_extra", "enable_prefix_caching"): True,
        ("vllm_extra", "mamba_ssm_cache_dtype"): "float32",
        ("enable_fp32_lm_head",): True,
    }
    issues = []
    for keys, expected in expected_config.items():
        actual = nested(config, *keys)
        if actual != expected:
            issues.append({"field": ".".join(keys), "expected": expected, "actual": actual})

    if len(models) != 1:
        issues.append({"field": "models.data", "expected_count": 1, "actual_count": len(models)})
    else:
        if models[0].get("id") != EXPECTED_MODEL:
            issues.append({"field": "models.data[0].id", "actual": models[0].get("id")})
        if models[0].get("max_model_len") != 262_144:
            issues.append({"field": "models.data[0].max_model_len", "actual": models[0].get("max_model_len")})

    startup_markers = {
        "tool_call_parser": "'tool_call_parser': 'qwen3_coder'",
        "reasoning_parser": "'reasoning_parser': 'nemotron_v3'",
        "max_model_len": "'max_model_len': 262144",
        "tensor_parallel_size": "tensor_parallel_size=8",
        "model_snapshot": "models--nvidia--NVIDIA-Nemotron-3-Super-120B-A12B-BF16/snapshots/",
    }
    for field, marker in startup_markers.items():
        if marker not in startup:
            issues.append({"field": f"startup.{field}", "issue": "expected marker is absent"})

    report = {
        "config": str(args.config.resolve()),
        "models": str(args.models.resolve()),
        "startup_log": str(args.startup_log.resolve()),
        "model": models[0].get("id") if len(models) == 1 else None,
        "max_model_len": models[0].get("max_model_len") if len(models) == 1 else None,
        "tool_call_parser": nested(config, "model", "tool_call_parser"),
        "reasoning_parser": nested(config, "model", "reasoning_parser"),
        "tensor_parallel_size": nested(config, "parallel", "tp"),
        "issues": issues,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.strict and issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
