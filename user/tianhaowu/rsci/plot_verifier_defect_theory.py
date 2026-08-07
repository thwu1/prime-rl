#!/usr/bin/env python3
"""Plot deterministic verifier-defect scaling mechanisms."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

DEFAULT_OUTPUT = Path(__file__).resolve().parent / "figures" / "verifier_defect_theory.svg"
DEFECT_RATES = (0.0025, 0.005, 0.01)
RATE_STYLES = (
    ("p = 0.25%", "#0072B2", "-"),
    ("p = 0.50%", "#D55E00", "--"),
    ("p = 1.00%", "#CC79A7", "-."),
)
H_STYLES = (
    (0.05, "#0072B2", "-"),
    (0.12, "#E69F00", "--"),
    (0.25, "#009E73", "-."),
    (0.50, "#CC79A7", ":"),
)
K = 128
X0 = 0.01
TARGET_SHARE = 0.90

plt.rcParams.update(
    {
        "axes.spines.right": False,
        "axes.spines.top": False,
        "font.size": 9.5,
        "legend.fontsize": 8.2,
        "svg.fonttype": "none",
        "svg.hashsalt": "rsci-verifier-defect-theory-v1",
    }
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def strict_dead_replicator(raw_exposure: np.ndarray, defect_rate: float, initial_share: float = X0) -> np.ndarray:
    """Exact flow of dx/dt = p*x*(1-x)."""
    odds = (1.0 - initial_share) / initial_share
    return 1.0 / (1.0 + odds * np.exp(-defect_rate * raw_exposure))


def scaled_threshold(target_share: float = TARGET_SHARE, initial_share: float = X0) -> float:
    return math.log((target_share / (1.0 - target_share)) * ((1.0 - initial_share) / initial_share))


def mixed_group_activation(defect_rate: np.ndarray, eligible_rate: float, group_size: int = K) -> np.ndarray:
    positive_rate = eligible_rate * defect_rate
    return 1.0 - (1.0 - positive_rate) ** group_size - positive_rate**group_size


def strict_base_rate(difficulty: np.ndarray) -> np.ndarray:
    return 0.35 * np.exp(-12.0 * difficulty)


def hackable_base_rate(difficulty: np.ndarray) -> np.ndarray:
    return 0.06 + 0.14 * difficulty


def defect_share(difficulty: np.ndarray, defect_rate: float) -> np.ndarray:
    strict_mass = strict_base_rate(difficulty)
    defect_mass = defect_rate * hackable_base_rate(difficulty)
    return defect_mass / (strict_mass + defect_mass)


def style_axis(axis: plt.Axes) -> None:
    axis.grid(axis="both", color="#D0D0D0", linewidth=0.7, alpha=0.65)
    axis.set_axisbelow(True)
    axis.tick_params(length=3.5)


def plot_replicator(axis: plt.Axes) -> None:
    raw_exposure = np.linspace(0.0, 3_000.0, 1_001)
    axis.axhline(X0, color="#4D4D4D", linestyle=":", linewidth=2.0, label="p = 0 (frozen)")
    for defect_rate, (label, color, linestyle) in zip(DEFECT_RATES, RATE_STYLES, strict=True):
        share = strict_dead_replicator(raw_exposure, defect_rate)
        axis.plot(raw_exposure, share, color=color, linestyle=linestyle, linewidth=2.2, label=label)

    z_threshold = scaled_threshold()
    axis.axhline(TARGET_SHARE, color="#6F6F6F", linestyle=(0, (2, 2)), linewidth=1.0)
    for defect_rate, (_, color, _) in zip(DEFECT_RATES, RATE_STYLES, strict=True):
        threshold = z_threshold / defect_rate
        axis.plot(threshold, TARGET_SHARE, marker="o", color=color, markersize=4.5, zorder=4)

    threshold_lines = "\n".join(
        f"{100 * defect_rate:.2f}%: T₉₀ = {z_threshold / defect_rate:,.0f}" for defect_rate in DEFECT_RATES
    )
    axis.text(
        0.025,
        0.97,
        f"dx/dT = p x(1−x)\nx(T) = [1 + 99 exp(−pT)]⁻¹\npT₉₀ = {z_threshold:.2f}\n{threshold_lines}",
        transform=axis.transAxes,
        va="top",
        ha="left",
        fontsize=8.0,
        bbox={"boxstyle": "round,pad=0.35", "facecolor": "white", "edgecolor": "#B0B0B0", "alpha": 0.94},
    )
    axis.set_xlim(0, 3_000)
    axis.set_ylim(-0.015, 1.02)
    axis.set_xlabel("raw training exposure T")
    axis.set_ylabel("hackable behavior share x_A(T)")
    axis.set_title("(a) Strict-dead replicator: any p > 0 eventually wins", loc="left", fontweight="bold")
    axis.legend(loc="center right", bbox_to_anchor=(0.995, 0.68), frameon=True)
    style_axis(axis)

    inset = axis.inset_axes((0.55, 0.20, 0.40, 0.29))
    scaled_exposure = np.linspace(0.0, 8.0, 300)
    collapsed = strict_dead_replicator(scaled_exposure, 1.0)
    for _, color, linestyle in RATE_STYLES:
        inset.plot(scaled_exposure, collapsed, color=color, linestyle=linestyle, linewidth=1.35)
    inset.axvline(z_threshold, color="#666666", linestyle=":", linewidth=0.9)
    inset.set_xlim(0, 8)
    inset.set_ylim(0, 1)
    inset.set_xlabel("scaled exposure pT", fontsize=7.3, labelpad=1)
    inset.set_ylabel("x_A", fontsize=7.3, labelpad=1)
    inset.set_title("exact curve collapse", fontsize=7.6, pad=2)
    inset.tick_params(labelsize=6.8, length=2)
    inset.grid(color="#DDDDDD", linewidth=0.5, alpha=0.7)


def plot_group_activation(axis: plt.Axes) -> None:
    defect_rate = np.linspace(0.0, 0.05, 700)
    for eligible_rate, color, linestyle in H_STYLES:
        activation = mixed_group_activation(defect_rate, eligible_rate)
        axis.plot(
            100.0 * defect_rate,
            activation,
            color=color,
            linestyle=linestyle,
            linewidth=2.2,
            label=f"h = {eligible_rate:.2f}",
        )
    for rate, (_, color, _) in zip(DEFECT_RATES, RATE_STYLES, strict=True):
        axis.axvline(100.0 * rate, color=color, linewidth=0.8, alpha=0.30)

    axis.text(
        0.97,
        0.05,
        "K = 128 independent rollouts\n"
        "per-rollout positive rate r = hp\n"
        "P(mixed) = 1 − (1−hp)ᴷ − (hp)ᴷ\n"
        "small r: P(mixed) ≈ Khp",
        transform=axis.transAxes,
        va="bottom",
        ha="right",
        fontsize=8.2,
        bbox={"boxstyle": "round,pad=0.35", "facecolor": "white", "edgecolor": "#B0B0B0", "alpha": 0.94},
    )
    axis.set_xlim(0, 5)
    axis.set_ylim(0, 0.97)
    axis.set_xlabel("verifier defect probability p (%)")
    axis.set_ylabel("probability of a trainable mixed group")
    axis.set_title("(b) Group activation is nonlinear in search width", loc="left", fontweight="bold")
    axis.legend(title="eligible behavior rate", loc="upper left", frameon=True)
    style_axis(axis)


def plot_base_rate_frontier(axis: plt.Axes) -> None:
    difficulty = np.linspace(0.0, 1.0, 800)
    axis.axhline(0.0, color="#4D4D4D", linestyle=":", linewidth=2.0, label="p = 0")
    for defect_rate, (label, color, linestyle) in zip(DEFECT_RATES, RATE_STYLES, strict=True):
        share = defect_share(difficulty, defect_rate)
        axis.plot(difficulty, share, color=color, linestyle=linestyle, linewidth=2.2, label=label)
        crossing_index = int(
            np.argmin(np.abs(strict_base_rate(difficulty) - defect_rate * hackable_base_rate(difficulty)))
        )
        crossing = difficulty[crossing_index]
        axis.plot(crossing, share[crossing_index], marker="o", color=color, markersize=4.5)
        axis.vlines(crossing, 0, share[crossing_index], color=color, linestyle=":", linewidth=0.8, alpha=0.65)

    axis.axhline(0.5, color="#6F6F6F", linestyle=(0, (2, 2)), linewidth=1.0)
    axis.text(
        0.03,
        0.97,
        "ILLUSTRATIVE — NOT FITTED DATA\n"
        "q(d) = 0.35 exp(−12d)   [strict mass]\n"
        "h(d) = 0.06 + 0.14d    [hackable mass]\n"
        "defect share = ph(d) / [q(d) + ph(d)]\n"
        "dots: q(d) = ph(d), hence 50% defect share",
        transform=axis.transAxes,
        va="top",
        ha="left",
        fontsize=8.0,
        bbox={"boxstyle": "round,pad=0.35", "facecolor": "#FFF7E6", "edgecolor": "#D89000", "alpha": 0.96},
    )
    axis.set_xlim(0, 1)
    axis.set_ylim(-0.015, 1.02)
    axis.set_xlabel("illustrative task difficulty d")
    axis.set_ylabel("share of accepted reward from defects")
    axis.set_title("(c) Toy base-rate frontier: tiny p can dominate", loc="left", fontweight="bold")
    axis.legend(loc="lower right", frameon=True)
    style_axis(axis)


def add_svg_accessibility(path: Path) -> None:
    svg = path.read_text(encoding="utf-8")
    marker = "<svg "
    if marker not in svg:
        raise ValueError(f"Generated output is not an SVG: {path}")
    svg = svg.replace(
        marker,
        '<svg role="img" aria-labelledby="verifier-defect-title verifier-defect-desc" ',
        1,
    )
    opening_end = svg.index(">", svg.index("<svg")) + 1
    title = "<title>Verifier defect scaling mechanisms</title>"
    accessible_title = '<title id="verifier-defect-title">Verifier defect scaling mechanisms</title>'
    if title in svg:
        svg = svg.replace(title, accessible_title, 1)
        accessible_text = ""
    else:
        accessible_text = f"\n  {accessible_title}"
    accessible_text += (
        '\n  <desc id="verifier-defect-desc">Three deterministic theory panels show strict-dead '
        "replicator collapse under positive defect probability, exact 128-sample mixed-group activation, "
        "and an explicitly illustrative—not fitted—base-rate frontier.</desc>"
    )
    svg = svg[:opening_end] + accessible_text + svg[opening_end:]
    path.write_text("\n".join(line.rstrip() for line in svg.splitlines()) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    figure, axes = plt.subplots(1, 3, figsize=(16.2, 5.25))
    figure.subplots_adjust(left=0.055, right=0.985, bottom=0.14, top=0.84, wspace=0.28)
    plot_replicator(axes[0])
    plot_group_activation(axes[1])
    plot_base_rate_frontier(axes[2])
    figure.suptitle(
        "Verifier defects: support discontinuity, group activation, and base-rate takeover",
        fontsize=14,
        fontweight="bold",
        y=0.965,
    )
    figure.text(
        0.5,
        0.025,
        "Deterministic theory curves. Panels (a–b) are exact under their stated assumptions; panel (c) is a labeled toy model.",
        ha="center",
        fontsize=9,
        color="#444444",
    )

    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(
        output,
        format="svg",
        metadata={
            "Title": "Verifier defect scaling mechanisms",
            "Description": "Exact strict-dead replicator and group-activation curves with an illustrative base-rate frontier.",
            "Creator": "RSCI deterministic theory plot",
            "Date": None,
        },
    )
    plt.close(figure)
    add_svg_accessibility(output)
    print(output)


if __name__ == "__main__":
    main()
