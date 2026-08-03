#!/usr/bin/env python
"""Plot progress for answer-filtered and strict-filtered frontier SFT tracks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt

plt.rcParams["svg.hashsalt"] = "rsci-frontier"
TRACKS = {
    "Answer filter": ("answer_only", "#2563eb"),
    "Strict filter": ("strict_graph", "#ea580c"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--answer-root", type=Path, required=True)
    parser.add_argument("--strict-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def metric_pass1(path: Path, verifier: str) -> float:
    metrics = load_json(path)
    return 100.0 * float(metrics[verifier]["total"]["unbiased"]["pass@1"])


def available_operations(root: Path) -> list[int]:
    state = load_json(root / "state.json")
    return sorted(int(operation) for operation in state["iterations"])


def main() -> None:
    args = parse_args()
    roots = {"Answer filter": args.answer_root, "Strict filter": args.strict_root}
    figure, axes = plt.subplots(1, 3, figsize=(12.8, 4.2), constrained_layout=True)
    all_operations: set[int] = set()

    for label, root in roots.items():
        gate_verifier, color = TRACKS[label]
        operations = available_operations(root)
        all_operations.update(operations)

        gate_x: list[int] = []
        gate_y: list[float] = []
        answer_post_x: list[int] = []
        answer_post_y: list[float] = []
        strict_post_x: list[int] = []
        strict_post_y: list[float] = []
        shard_x: list[int] = []
        shard_y: list[float] = []
        for operation in operations:
            iteration = root / "iterations" / f"op{operation}"
            pre_metrics = iteration / "pre_eval" / "metrics.json"
            post_metrics = iteration / "post_selected_eval" / "metrics.json"
            if not post_metrics.exists():
                post_metrics = iteration / "post_eval" / "metrics.json"
            collection_manifest = iteration / "collection" / "manifest.json"
            if pre_metrics.exists():
                gate_x.append(operation)
                gate_y.append(metric_pass1(pre_metrics, gate_verifier))
            if post_metrics.exists():
                answer_post_x.append(operation)
                answer_post_y.append(metric_pass1(post_metrics, "answer_only"))
                strict_post_x.append(operation)
                strict_post_y.append(metric_pass1(post_metrics, "strict_graph"))
            if collection_manifest.exists():
                manifest = load_json(collection_manifest)
                shard_x.append(operation)
                shard_y.append(100.0 * manifest["accepted_strict"] / manifest["accepted"])

        axes[0].plot(gate_x, gate_y, color=color, marker="o", linewidth=2, label=label)
        axes[1].plot(
            answer_post_x,
            answer_post_y,
            color=color,
            marker="o",
            linewidth=2,
            label=f"{label}: answer",
        )
        axes[1].plot(
            strict_post_x,
            strict_post_y,
            color=color,
            marker="s",
            linestyle="--",
            linewidth=2,
            label=f"{label}: strict",
        )
        axes[2].plot(shard_x, shard_y, color=color, marker="o", linewidth=2, label=label)

    axes[0].axhline(1.0, color="#444444", linestyle=":", label="1% stop gate")
    axes[0].set_title("Pre-training frontier gate")
    axes[0].set_ylabel("gate pass@1 (%)")
    axes[1].set_title("Post-SFT in-distribution")
    axes[1].set_ylabel("post pass@1 (%)")
    axes[2].set_title("Accepted shard reasoning quality")
    axes[2].set_ylabel("strict share (%)")

    ticks = sorted(all_operations)
    if len(ticks) > 16:
        ticks = ticks[::2]
        final_operation = max(all_operations)
        if ticks[-1] != final_operation:
            ticks.append(final_operation)
    for axis in axes:
        axis.set_xlabel("operation")
        axis.set_xticks(ticks)
        axis.set_ylim(0, 100.5)
        axis.grid(alpha=0.3, linestyle="--")
        axis.legend(fontsize=8)
    figure.suptitle("Iterative frontier SFT progress (unbiased estimator)")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    metadata = {"Date": None} if args.output.suffix.lower() == ".svg" else None
    figure.savefig(args.output, bbox_inches="tight", metadata=metadata)
    if args.output.suffix.lower() == ".svg":
        lines = args.output.read_text(encoding="utf-8").splitlines()
        args.output.write_text("\n".join(line.rstrip() for line in lines) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
