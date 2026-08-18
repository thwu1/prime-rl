#!/usr/bin/env python
"""Plot strict ID and OOD-mid pass@k curves from RSCI metrics files."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import matplotlib.pyplot as plt

PASS_AT = [1, 2, 4, 8, 16, 32, 64, 128]
plt.rcParams["svg.hashsalt"] = "rsci-figure3"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--series",
        action="append",
        nargs=3,
        metavar=("LABEL", "ID_METRICS", "OOD_METRICS"),
        required=True,
    )
    parser.add_argument("--estimator", choices=["unbiased", "empirical"], default="unbiased")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def load_curve(path: Path, panel: str, estimator: str) -> list[float]:
    metrics = json.loads(path.read_text(encoding="utf-8"))
    strict = metrics["strict_graph"]
    aggregate = strict.get("weighted_total", strict["total"]) if panel == "id" else strict["total"]
    return [100.0 * aggregate[estimator][f"pass@{k}"] for k in PASS_AT]


def main() -> None:
    args = parse_args()
    figure, axes = plt.subplots(1, 2, figsize=(9.2, 4.0), sharex=True)
    x_values = list(range(len(PASS_AT)))
    minimum_id = 100.0
    for label, id_path, ood_path in args.series:
        id_curve = load_curve(Path(id_path), "id", args.estimator)
        minimum_id = min(minimum_id, *id_curve)
        axes[0].plot(x_values, id_curve, marker="o", label=label)
        axes[1].plot(x_values, load_curve(Path(ood_path), "ood", args.estimator), marker="o", label=label)
    for axis, title in zip(axes, ("ID (op=2-10)", "OOD-mid (op=11-14)"), strict=True):
        axis.set_title(title)
        axis.set_xticks(x_values, PASS_AT)
        axis.set_xlabel("pass@k")
        axis.grid(alpha=0.3, linestyle="--")
    axes[0].set_ylabel("strict performance (%)")
    axes[0].set_ylim(max(0, 5 * (math.floor(minimum_id / 5) - 1)), 100.5)
    axes[1].set_ylim(0, 100)
    handles, labels = axes[0].get_legend_handles_labels()
    figure.legend(handles, labels, loc="lower center", ncol=min(3, len(labels)))
    figure.suptitle(f"prime-rl reproduction ({args.estimator} estimator)")
    figure.tight_layout(rect=(0, 0.12, 1, 1))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    metadata = {"Date": None} if args.output.suffix.lower() == ".svg" else None
    figure.savefig(args.output, bbox_inches="tight", metadata=metadata)
    if args.output.suffix.lower() == ".svg":
        lines = args.output.read_text(encoding="utf-8").splitlines()
        args.output.write_text("\n".join(line.rstrip() for line in lines) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
