#!/usr/bin/env python
"""Plot OP28 strict pass@k for strict-filter SFT and matched golden SFT."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt

PASS_AT = [1, 2, 4, 8, 16, 32, 64, 128]
plt.rcParams["svg.hashsalt"] = "rsci-oracle-op28"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict-pre", type=Path, required=True)
    parser.add_argument("--strict-post", type=Path, required=True)
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def load_curve(path: Path) -> list[float]:
    metrics = json.loads(path.read_text(encoding="utf-8"))
    unbiased = metrics["strict_graph"]["total"]["unbiased"]
    return [100.0 * float(unbiased[f"pass@{k}"]) for k in PASS_AT]


def main() -> None:
    args = parse_args()
    curves = (
        ("Before OP28 SFT", load_curve(args.strict_pre), "#8b95a5"),
        ("Strict-filter SFT", load_curve(args.strict_post), "#e07a5f"),
        ("Matched golden SFT", load_curve(args.oracle), "#3d7ea6"),
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
    axis.set_title("OP28: canonical gold targets outperform strict-filtered trajectories")
    figure.tight_layout()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.output, bbox_inches="tight", metadata={"Date": None})
    lines = args.output.read_text(encoding="utf-8").splitlines()
    args.output.write_text("\n".join(line.rstrip() for line in lines) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
