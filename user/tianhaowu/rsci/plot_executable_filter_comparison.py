#!/usr/bin/env python
"""Plot the OP28 strict pass@k executable-filter and oracle comparison."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt

PASS_AT = [1, 2, 4, 8, 16, 32, 64, 128]
plt.rcParams["svg.hashsalt"] = "rsci-executable-filter-op28"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def curve(comparison: dict, treatment: str) -> list[float]:
    metrics = comparison[treatment]["strict_graph"]
    return [100.0 * float(metrics[f"pass@{k}"]) for k in PASS_AT]


def main() -> None:
    args = parse_args()
    comparison = json.loads(args.comparison.read_text(encoding="utf-8"))
    curves = (
        ("Original strict filter", curve(comparison, "original_strict_filter"), "#e07a5f"),
        ("Executable-filtered strict", curve(comparison, "executable_filtered_strict"), "#6f8f55"),
        ("Matched canonical oracle", curve(comparison, "matched_canonical_oracle"), "#3d7ea6"),
    )
    x_values = list(range(len(PASS_AT)))
    figure, axis = plt.subplots(figsize=(7.4, 4.3))
    for label, values, color in curves:
        axis.plot(x_values, values, marker="o", linewidth=2.2, label=label, color=color)
    axis.set_xticks(x_values, PASS_AT)
    axis.set_xlabel("k")
    axis.set_ylabel("strict pass@k (%)")
    axis.set_ylim(0, 17)
    axis.grid(alpha=0.3, linestyle="--")
    axis.legend(loc="upper left")
    axis.set_title("OP28: execution filtering does not close the oracle gap")
    figure.tight_layout()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.output, bbox_inches="tight", metadata={"Date": None})
    lines = args.output.read_text(encoding="utf-8").splitlines()
    args.output.write_text("\n".join(line.rstrip() for line in lines) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
