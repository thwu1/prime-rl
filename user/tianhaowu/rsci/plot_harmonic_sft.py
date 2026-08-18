#!/usr/bin/env python
"""Plot the pretrained, unweighted, and harmonic-SFT OP15-18 pass@k curves."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt

PASS_AT = [1, 2, 4, 8, 16, 32, 64, 128]
CURVES = {
    "Pretrained": ("base", "#7c8798", "--"),
    "Unweighted SFT": ("baseline", "#111827", "-"),
    "Harmonic K=4": ("k4", "#2563eb", "-"),
    "Harmonic K=8": ("k8", "#0891b2", "-"),
    "Harmonic K=16": ("k16", "#059669", "-"),
    "Harmonic K=32": ("k32", "#ca8a04", "-"),
    "Harmonic K=64": ("k64", "#dc2626", "-"),
}
plt.rcParams["svg.hashsalt"] = "rsci-harmonic-sft"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def load_curve(root: Path, name: str) -> list[float]:
    metrics = json.loads((root / "eval" / name / "metrics.json").read_text(encoding="utf-8"))
    values = metrics["answer_only"]["total"]["unbiased"]
    return [100.0 * float(values[f"pass@{k}"]) for k in PASS_AT]


def main() -> None:
    args = parse_args()
    curves = {label: load_curve(args.root, name) for label, (name, _, _) in CURVES.items()}
    baseline = curves["Unweighted SFT"]
    x_values = list(range(len(PASS_AT)))
    figure, axes = plt.subplots(1, 2, figsize=(12.2, 4.4), constrained_layout=True)

    for label, values in curves.items():
        _, color, linestyle = CURVES[label]
        linewidth = 2.5 if label in {"Unweighted SFT", "Harmonic K=4", "Harmonic K=64"} else 1.8
        axes[0].plot(
            x_values,
            values,
            color=color,
            linestyle=linestyle,
            linewidth=linewidth,
            marker="o",
            markersize=4.5,
            label=label,
        )
        if label.startswith("Harmonic"):
            delta = [value - reference for value, reference in zip(values, baseline, strict=True)]
            axes[1].plot(x_values, delta, color=color, linewidth=2, marker="o", markersize=4, label=label)

    for axis in axes:
        axis.set_xticks(x_values, PASS_AT)
        axis.set_xlabel("inference budget k")
        axis.grid(alpha=0.3, linestyle="--")
    axes[0].set_ylabel("answer pass@k (%)")
    axes[0].set_title("OP15–18 out-of-distribution performance")
    axes[0].legend(fontsize=8, ncols=2)
    axes[1].axhline(0, color="#6b7280", linewidth=1, linestyle=":")
    axes[1].set_ylabel("gain over unweighted SFT (percentage points)")
    axes[1].set_title("Harmonic weighting gain")
    axes[1].legend(fontsize=8, ncols=2)

    figure.suptitle("Harmonic SFT shifts improvement toward larger sampling budgets")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    metadata = {"Date": None} if args.output.suffix.lower() == ".svg" else None
    figure.savefig(args.output, bbox_inches="tight", metadata=metadata)
    if args.output.suffix.lower() == ".svg":
        lines = args.output.read_text(encoding="utf-8").splitlines()
        args.output.write_text("\n".join(line.rstrip() for line in lines) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
