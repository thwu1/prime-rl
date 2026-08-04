#!/usr/bin/env python
"""Plot completed OP11-25 strict pass@1 evaluations for one RL run."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import matplotlib.pyplot as plt
import orjson

OPS = tuple(range(11, 26))
plt.rcParams["svg.hashsalt"] = "rsci-rl-strict-eval"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rollouts-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def load_score(path: Path) -> float:
    strict_scores: list[float] = []
    with path.open("rb") as handle:
        for line in handle:
            row = orjson.loads(line)
            strict = float(row["metrics"]["strict_dependency_graph_reward"])
            reward = float(row["rewards"]["reward"])
            if reward != strict:
                raise ValueError(f"RL reward does not match strict reward in {path}")
            strict_scores.append(strict)
    if len(strict_scores) != 200:
        raise ValueError(f"Expected 200 rows in {path}, found {len(strict_scores)}")
    return 100.0 * sum(strict_scores) / len(strict_scores)


def load_complete_evals(root: Path) -> dict[int, list[float]]:
    evaluations: dict[int, list[float]] = {}
    step_dirs = sorted(root.glob("step_*"), key=lambda path: int(path.name.removeprefix("step_")))
    for step_dir in step_dirs:
        paths = [step_dir / f"eval_rollouts_heldout-op{op}-strict.jsonl" for op in OPS]
        if not all(path.is_file() for path in paths):
            continue
        step = int(step_dir.name.removeprefix("step_"))
        evaluations[step] = [load_score(path) for path in paths]
    if not evaluations:
        raise ValueError(f"No complete OP11-25 evaluations found under {root}")
    return evaluations


def main() -> None:
    args = parse_args()
    evaluations = load_complete_evals(args.rollouts_root)
    legend_columns = max(1, math.ceil(len(evaluations) / 12))
    figure_width = 10.5 + 2.0 * legend_columns
    figure, axis = plt.subplots(figsize=(figure_width, 5.2))
    figure.subplots_adjust(left=0.07, right=10.3 / figure_width, bottom=0.13, top=0.9)
    colors = plt.cm.viridis_r([index / max(1, len(evaluations) - 1) for index in range(len(evaluations))])

    for color, (step, scores) in zip(colors, evaluations.items(), strict=True):
        axis.plot(OPS, scores, marker="o", linewidth=2.2, color=color, label=f"step {step}")

    axis.set_xticks(OPS)
    axis.set_xlabel("operation count")
    axis.set_ylabel("strict pass@1 (%)")
    axis.set_title("Strict-reward GRPO held-out validation")
    axis.grid(alpha=0.3, linestyle="--")
    axis.legend(
        title="evaluation",
        loc="upper left",
        bbox_to_anchor=(1.01, 1.0),
        ncols=legend_columns,
        fontsize=8,
        columnspacing=1.0,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    metadata = {"Date": None} if args.output.suffix.lower() == ".svg" else None
    figure.savefig(args.output, bbox_inches="tight", metadata=metadata)
    if args.output.suffix.lower() == ".svg":
        lines = args.output.read_text(encoding="utf-8").splitlines()
        args.output.write_text("\n".join(line.rstrip() for line in lines) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
