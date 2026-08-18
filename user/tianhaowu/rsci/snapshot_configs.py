#!/usr/bin/env python
"""Write immutable input and resolved prime-rl configs for an RSCI evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
import tomllib
from pathlib import Path

import tomli_w

from prime_rl.configs.inference import InferenceConfig
from prime_rl.utils.config import cli


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("eval_config", type=Path)
    return parser.parse_args()


def write_toml(path: Path, payload: dict) -> None:
    partial = path.with_suffix(path.suffix + ".partial")
    with partial.open("wb") as handle:
        tomli_w.dump(payload, handle)
    partial.replace(path)


def main() -> None:
    args = parse_args()
    eval_bytes = args.eval_config.read_bytes()
    eval_config = tomllib.loads(eval_bytes.decode())
    infer_path = Path(eval_config["infer_config"])
    infer_bytes = infer_path.read_bytes()
    output_dir = Path(eval_config["eval"]["output_dir"])
    config_dir = output_dir / "configs"
    config_dir.mkdir(parents=True, exist_ok=True)

    inference = cli(InferenceConfig, args=["@", str(infer_path)])
    if eval_config["eval"]["model"] != inference.model.name:
        raise ValueError("Eval and inference configs must reference the same model")
    write_toml(config_dir / "eval.toml", eval_config)
    write_toml(
        config_dir / "inference.toml",
        inference.model_dump(exclude_none=True, mode="json"),
    )
    manifest = {
        "eval_config_source": str(args.eval_config.resolve()),
        "eval_config_sha256": hashlib.sha256(eval_bytes).hexdigest(),
        "inference_config_source": str(infer_path.resolve()),
        "inference_config_sha256": hashlib.sha256(infer_bytes).hexdigest(),
    }
    manifest_path = config_dir / "manifest.json"
    partial = manifest_path.with_suffix(".json.partial")
    partial.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    partial.replace(manifest_path)
    print(config_dir)


if __name__ == "__main__":
    main()
