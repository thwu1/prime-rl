#!/usr/bin/env python
"""Select the stable SFT checkpoint with minimum held-out validation loss."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tomllib
from pathlib import Path
from typing import Any

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
VALIDATION_RE = re.compile(r"Validation \| Step (\d+) \| Loss ([-+0-9.eE]+)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sft-output", type=Path, required=True)
    parser.add_argument("--validation-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    partial.replace(path)


def parse_validation_losses(log_path: Path) -> dict[int, float]:
    losses: dict[int, float] = {}
    for line in log_path.read_text(encoding="utf-8").splitlines():
        match = VALIDATION_RE.search(ANSI_RE.sub("", line))
        if match is None:
            continue
        step = int(match.group(1))
        loss = float(match.group(2))
        if step in losses and losses[step] != loss:
            raise ValueError(f"Conflicting validation losses for step {step} in {log_path}")
        losses[step] = loss
    return losses


def main() -> None:
    args = parse_args()
    if args.output.exists():
        print(args.output.read_text(encoding="utf-8"))
        return

    config_path = args.sft_output / "configs" / "sft.toml"
    log_path = args.sft_output / "logs" / "trainer.log"
    with config_path.open("rb") as handle:
        config = tomllib.load(handle)
    if "val" not in config:
        raise ValueError(f"SFT config has no validation dataset: {config_path}")
    if config["val"].get("eval_on_start", False):
        raise ValueError("Frontier checkpoint selection excludes the untrained step-0 model")
    interval = int(config["val"]["interval"])
    if int(config["ckpt"]["interval"]) != interval:
        raise ValueError("Validation and weight-checkpoint intervals must match")
    max_steps = int(config["max_steps"])
    expected_steps = set(range(interval, max_steps, interval)) | {max_steps}
    losses = parse_validation_losses(log_path)
    if set(losses) != expected_steps:
        raise ValueError(f"Expected validation steps {sorted(expected_steps)}, found {sorted(losses)}")

    candidates: list[dict[str, Any]] = []
    for step in sorted(losses):
        checkpoint = args.sft_output / "weights" / f"step_{step}"
        stable = checkpoint / "STABLE"
        if not stable.exists():
            raise FileNotFoundError(f"Validation step {step} has no stable checkpoint: {checkpoint}")
        candidates.append({"step": step, "validation_loss": losses[step], "checkpoint": str(checkpoint)})
    selected = min(candidates, key=lambda candidate: (candidate["validation_loss"], candidate["step"]))
    repo_root = Path(__file__).resolve().parents[3]
    payload = {
        "selection_rule": "minimum held-out token-weighted validation loss; earliest step breaks ties",
        "sft_output": str(args.sft_output.resolve()),
        "sft_config": str(config_path.resolve()),
        "sft_config_sha256": file_sha256(config_path),
        "trainer_log": str(log_path.resolve()),
        "trainer_log_sha256": file_sha256(log_path),
        "validation_manifest": str(args.validation_manifest.resolve()),
        "validation_manifest_sha256": file_sha256(args.validation_manifest),
        "validation_interval": interval,
        "max_steps": max_steps,
        "candidates": candidates,
        "selected_step": selected["step"],
        "selected_validation_loss": selected["validation_loss"],
        "selected_checkpoint": selected["checkpoint"],
        "implementation_sha256": {
            "frontier_select_checkpoint.py": file_sha256(Path(__file__)),
            "src/prime_rl/trainer/sft/train.py": file_sha256(repo_root / "src/prime_rl/trainer/sft/train.py"),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.output, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
