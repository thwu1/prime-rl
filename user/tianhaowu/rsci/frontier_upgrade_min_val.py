#!/usr/bin/env python
"""Upgrade a paused final-checkpoint frontier track to minimum-validation-loss selection."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import tomli_w


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    return parser.parse_args()


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")


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


def write_toml(path: Path, payload: dict[str, Any]) -> None:
    partial = path.with_suffix(path.suffix + ".partial")
    with partial.open("wb") as handle:
        tomli_w.dump(payload, handle)
    partial.replace(path)


def copy_once(source: Path, destination: Path) -> None:
    if destination.exists():
        if source.read_bytes() != destination.read_bytes():
            raise ValueError(f"Archive already exists with different contents: {destination}")
        return
    shutil.copy2(source, destination)


def assert_no_active_jobs(track: str) -> None:
    result = subprocess.run(
        ["squeue", "--noheader", "--name", f"rsci-frontier-{track}", "--format=%A"],
        capture_output=True,
        text=True,
        check=True,
    )
    if result.stdout.strip():
        raise RuntimeError(f"Track still has an active watcher: {result.stdout.strip()}")


def main() -> None:
    args = parse_args()
    config_path = args.config.resolve()
    with config_path.open("rb") as handle:
        resolved_config = tomllib.load(handle)
    frontier = resolved_config["frontier"]
    root = Path(frontier["experiment_root"])
    state_path = root / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    config_sha256 = file_sha256(config_path)
    if state.get("protocol_version") == "min_val_v2":
        if state["source_config_sha256"] != config_sha256:
            raise ValueError("Already-upgraded state does not match the current config")
        print(json.dumps(state, indent=2, sort_keys=True))
        return

    assert_no_active_jobs(str(frontier["track"]))
    if state["track"] != frontier["track"]:
        raise ValueError("State and config tracks differ")
    start_operation = int(frontier["start_operation"])
    iteration = state["iterations"][str(start_operation)]
    collection_manifest_path = Path(iteration["collection_manifest"])
    collection_manifest = json.loads(collection_manifest_path.read_text(encoding="utf-8"))
    if int(collection_manifest["accepted"]) != int(frontier["target_accepted"]):
        raise ValueError("Existing training shard is not the configured exact size")
    if int(collection_manifest["operation"]) != start_operation:
        raise ValueError("Existing training shard has the wrong operation")
    dataset_manifest_path = Path(iteration["dataset_manifest"])
    dataset_manifest = json.loads(dataset_manifest_path.read_text(encoding="utf-8"))
    if int(dataset_manifest["rows"]) != int(frontier["target_accepted"]):
        raise ValueError("Existing cumulative training dataset has the wrong size")
    next_iteration_dir = root / "iterations" / f"op{start_operation + 1}"
    next_iteration_archive = root / "iterations" / f"op{start_operation + 1}_final_checkpoint_v1"
    next_manifest = next_iteration_dir / "collection" / "manifest.json"
    if next_manifest.exists():
        raise ValueError(f"A later training collection already completed: {next_manifest}")
    if next_iteration_dir.exists() and next_iteration_archive.exists():
        raise ValueError(f"Later-operation archive already exists: {next_iteration_archive}")
    for path in (
        root / "iterations" / f"op{start_operation}" / "validation_collection" / "manifest.json",
        root / "iterations" / f"op{start_operation}" / "model_min_val" / "weights",
        root / "iterations" / f"op{start_operation}" / "checkpoint_selection.json",
    ):
        if path.exists():
            raise ValueError(f"Minimum-validation protocol has already written artifacts: {path}")

    copy_once(state_path, root / "state_final_checkpoint_v1.json")
    copy_once(root / "frontier.toml", root / "frontier_final_checkpoint_v1.toml")
    if next_iteration_dir.exists():
        next_iteration_dir.rename(next_iteration_archive)
    write_toml(root / "frontier.toml", resolved_config)

    superseded = {
        "protocol": "final one-epoch checkpoint",
        "trained_model": iteration["trained_model"],
        "post_eval_metrics": iteration["post_eval_metrics"],
        "state_archive": str((root / "state_final_checkpoint_v1.json").resolve()),
        "config_archive": str((root / "frontier_final_checkpoint_v1.toml").resolve()),
    }
    upgraded_iteration = {
        key: value
        for key, value in iteration.items()
        if key not in {"trained_model", "post_eval_metrics", "sft_status_recorded"}
    }
    upgraded_iteration["superseded_final_checkpoint"] = superseded
    implementation_names = (
        "figure3_eval.py",
        "frontier_build_dataset.py",
        "frontier_collect.py",
        "frontier_loop.py",
        "frontier_select_checkpoint.py",
        "generate.py",
        "solution_graph.py",
    )
    script_dir = Path(__file__).parent
    implementation_sha256 = {name: file_sha256(script_dir / name) for name in implementation_names}
    implementation_sha256["src/prime_rl/trainer/sft/train.py"] = file_sha256(
        Path(__file__).resolve().parents[3] / "src/prime_rl/trainer/sft/train.py"
    )
    upgraded = {
        "track": frontier["track"],
        "filter_mode": frontier["filter_mode"],
        "gate_metric": frontier["gate_metric"],
        "protocol_version": "min_val_v2",
        "source_config": str(config_path),
        "source_config_sha256": config_sha256,
        "status": "running",
        "current_operation": start_operation,
        "jobs": {},
        "iterations": {str(start_operation): upgraded_iteration},
        "created_at": state["created_at"],
        "upgraded_at": now(),
        "implementation_sha256": implementation_sha256,
    }
    write_json(state_path, upgraded)
    with (root / "STATUS.md").open("a", encoding="utf-8") as handle:
        handle.write(f"\n## {now()} — minimum-validation protocol activated\n\n")
        handle.write(f"- operation reset for checkpoint selection: `{start_operation}`\n")
        handle.write(f"- preserved training traces: `{collection_manifest['accepted']}`\n")
        handle.write(f"- preserved previous state: `{root / 'state_final_checkpoint_v1.json'}`\n")
        handle.write("- later-operation training shards preserved: `none existed`\n")
        if next_iteration_archive.exists():
            handle.write(f"- superseded later-operation diagnostics: `{next_iteration_archive}`\n")
    print(json.dumps(upgraded, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
