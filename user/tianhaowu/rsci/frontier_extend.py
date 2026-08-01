#!/usr/bin/env python
"""Resume a completed frontier track over a generated evaluation extension."""

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

ALLOWED_NEW_FIELDS = {
    "generated_eval_context_mixture",
    "generated_eval_mode_mixture",
    "generated_eval_seed",
    "generated_validation_data_dir",
    "generator_op_max",
}


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


def assert_no_active_watcher(track: str) -> None:
    result = subprocess.run(
        ["squeue", "--noheader", "--name", f"rsci-frontier-{track}", "--format=%A"],
        capture_output=True,
        text=True,
        check=True,
    )
    if result.stdout.strip():
        raise RuntimeError(f"Track still has an active watcher: {result.stdout.strip()}")


def validate_config_change(previous: dict[str, Any], extended: dict[str, Any]) -> tuple[int, int]:
    previous_max = int(previous["max_operation"])
    extended_max = int(extended["max_operation"])
    if extended_max <= previous_max:
        raise ValueError("Extended max_operation must be greater than the previous maximum")
    for key, value in previous.items():
        if key != "max_operation" and extended.get(key) != value:
            raise ValueError(f"Frontier extension changed frozen field {key!r}")
    unexpected = set(extended) - set(previous) - ALLOWED_NEW_FIELDS
    if unexpected:
        raise ValueError(f"Frontier extension added unsupported fields: {sorted(unexpected)}")
    missing = ALLOWED_NEW_FIELDS - set(extended)
    if missing:
        raise ValueError(f"Frontier extension is missing fields: {sorted(missing)}")
    if int(extended["generator_op_max"]) < extended_max:
        raise ValueError("generator_op_max must cover the extended maximum operation")
    return previous_max, extended_max


def implementation_hashes(script_dir: Path) -> dict[str, str]:
    names = (
        "figure3_eval.py",
        "frontier_build_dataset.py",
        "frontier_collect.py",
        "frontier_extend.py",
        "frontier_loop.py",
        "frontier_select_checkpoint.py",
        "generate.py",
        "solution_graph.py",
    )
    hashes = {name: file_sha256(script_dir / name) for name in names}
    hashes["src/prime_rl/trainer/sft/train.py"] = file_sha256(
        Path(__file__).resolve().parents[3] / "src/prime_rl/trainer/sft/train.py"
    )
    return hashes


def main() -> None:
    args = parse_args()
    config_path = args.config.resolve()
    with config_path.open("rb") as handle:
        extended_config = tomllib.load(handle)
    frontier = extended_config["frontier"]
    root = Path(frontier["experiment_root"])
    state_path = root / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    config_sha256 = file_sha256(config_path)
    if state.get("source_config_sha256") == config_sha256 and state["status"] == "running":
        print(json.dumps(state, indent=2, sort_keys=True))
        return

    assert_no_active_watcher(str(frontier["track"]))
    if state["track"] != frontier["track"]:
        raise ValueError("State and config tracks differ")
    if state["status"] != "max_operation_exhausted":
        raise ValueError(f"Track must be max_operation_exhausted, found {state['status']!r}")
    with (root / "frontier.toml").open("rb") as handle:
        previous_config = tomllib.load(handle)
    previous_max, extended_max = validate_config_change(previous_config["frontier"], frontier)
    if int(state["current_operation"]) != previous_max + 1:
        raise ValueError("State current_operation does not follow the previous maximum")
    expected_operations = set(range(int(frontier["start_operation"]), previous_max + 1))
    if {int(operation) for operation in state["iterations"]} != expected_operations:
        raise ValueError("State does not contain exactly the completed operation range")
    for operation in expected_operations:
        iteration = state["iterations"][str(operation)]
        for field in ("trained_model", "post_selected_eval_metrics"):
            if field not in iteration or not Path(iteration[field]).exists():
                raise ValueError(f"Completed op{operation} is missing {field}")

    state_archive = root / f"state_op{previous_max}_v1.json"
    config_archive = root / f"frontier_op{previous_max}_v1.toml"
    copy_once(state_path, state_archive)
    copy_once(root / "frontier.toml", config_archive)
    write_toml(root / "frontier.toml", extended_config)

    extension = {
        "extended_at": now(),
        "previous_max_operation": previous_max,
        "max_operation": extended_max,
        "generator_op_max": int(frontier["generator_op_max"]),
        "generated_validation_data_dir": str(Path(frontier["generated_validation_data_dir"]).resolve()),
        "state_archive": str(state_archive.resolve()),
        "config_archive": str(config_archive.resolve()),
    }
    state.setdefault("extension_history", []).append(extension)
    state["protocol_version"] = "min_val_generated_eval_v3"
    state["source_config"] = str(config_path)
    state["source_config_sha256"] = config_sha256
    state["status"] = "running"
    state.pop("completed_at", None)
    state["implementation_sha256"] = implementation_hashes(Path(__file__).parent)
    write_json(state_path, state)
    with (root / "STATUS.md").open("a", encoding="utf-8") as handle:
        handle.write(f"\n## {now()} — generated frontier extension activated\n\n")
        handle.write(f"- previous maximum operation: `{previous_max}`\n")
        handle.write(f"- extended maximum operation: `{extended_max}`\n")
        handle.write(f"- resumed operation: `{state['current_operation']}`\n")
        handle.write(f"- generator op_max: `{frontier['generator_op_max']}`\n")
        handle.write(f"- generated evaluation root: `{frontier['generated_validation_data_dir']}`\n")
        handle.write(f"- preserved previous state: `{state_archive}`\n")
    print(json.dumps(state, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
