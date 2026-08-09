#!/usr/bin/env python3
"""Freeze fixed-point predictions for verifier-filtered iterative SFT."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import brentq, root

SCHEMA_VERSION = 1
DOSES = (0.0, 0.01, 0.05, 0.10)
plt.rcParams["svg.hashsalt"] = "rsci-iterative-sft-phase-map"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-svg", type=Path, required=True)
    return parser.parse_args()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def binomial_tail_map(x: float, probability: float, samples: int, hits: int) -> float:
    q = probability * x
    return 1.0 - math.fsum(
        math.comb(samples, count) * q**count * (1.0 - q) ** (samples - count) for count in range(hits)
    )


def map_derivative(x: float, probability: float, samples: int, hits: int) -> float:
    q = probability * x
    return probability * samples * math.comb(samples - 1, hits - 1) * q ** (hits - 1) * (1.0 - q) ** (samples - hits)


def two_hit_saddle(samples: int) -> tuple[float, float]:
    solution = root(
        lambda values: (
            binomial_tail_map(values[0], values[1], samples, 2) - values[0],
            map_derivative(values[0], values[1], samples, 2) - 1.0,
        ),
        np.asarray((0.54, 3.35 / samples)),
    )
    if not solution.success:
        raise RuntimeError(solution.message)
    x_value, probability = (float(value) for value in solution.x)
    if not 0.0 < x_value < 1.0 or not 0.0 < probability < 1.0:
        raise ValueError(f"Invalid two-hit saddle: x={x_value}, p={probability}")
    return probability, x_value


def one_hit_fixed_points(samples: int, probability: float) -> list[dict[str, Any]]:
    derivative = samples * probability
    points = [{"x": 0.0, "derivative": derivative, "stable": derivative < 1.0}]
    if derivative <= 1.0:
        return points
    positive = brentq(
        lambda x: binomial_tail_map(x, probability, samples, 1) - x,
        1e-12,
        1.0,
    )
    positive_derivative = map_derivative(positive, probability, samples, 1)
    points.append(
        {
            "x": positive,
            "derivative": positive_derivative,
            "stable": positive_derivative < 1.0,
        }
    )
    return points


def two_hit_fixed_points(samples: int, probability: float, critical: tuple[float, float]) -> list[dict[str, Any]]:
    critical_probability, critical_x = critical
    points = [{"x": 0.0, "derivative": 0.0, "stable": True}]
    if probability < critical_probability:
        return points
    if math.isclose(probability, critical_probability, rel_tol=0.0, abs_tol=1e-12):
        points.append({"x": critical_x, "derivative": 1.0, "stable": False, "semistable": True})
        return points
    low = brentq(
        lambda x: binomial_tail_map(x, probability, samples, 2) - x,
        1e-12,
        critical_x,
    )
    high = brentq(
        lambda x: binomial_tail_map(x, probability, samples, 2) - x,
        critical_x,
        1.0,
    )
    for x_value in (low, high):
        derivative = map_derivative(x_value, probability, samples, 2)
        points.append({"x": x_value, "derivative": derivative, "stable": derivative < 1.0})
    return points


def write_figure(output: Path, two_hit_critical: tuple[float, float]) -> None:
    one_samples = 16
    two_samples = 128
    one_critical = 1.0 / one_samples
    two_critical_probability, two_critical_x = two_hit_critical
    probabilities = np.linspace(0.0, 0.12, 481)

    one_positive = np.full_like(probabilities, np.nan)
    for index, probability in enumerate(probabilities):
        if probability > one_critical:
            one_positive[index] = one_hit_fixed_points(one_samples, float(probability))[-1]["x"]

    two_low = np.full_like(probabilities, np.nan)
    two_high = np.full_like(probabilities, np.nan)
    for index, probability in enumerate(probabilities):
        if probability > two_critical_probability:
            points = two_hit_fixed_points(two_samples, float(probability), two_hit_critical)
            two_low[index] = points[1]["x"]
            two_high[index] = points[2]["x"]

    figure, axes = plt.subplots(1, 2, figsize=(10.5, 4.2), sharey=True)
    figure.subplots_adjust(left=0.08, right=0.98, bottom=0.16, top=0.82, wspace=0.16)
    axes[0].plot(
        probabilities[probabilities <= one_critical],
        np.zeros(sum(probabilities <= one_critical)),
        color="#1f1f1f",
        linewidth=2.2,
        label="stable",
    )
    axes[0].plot(
        probabilities[probabilities >= one_critical],
        np.zeros(sum(probabilities >= one_critical)),
        color="#777777",
        linewidth=1.8,
        linestyle="--",
        label="unstable",
    )
    axes[0].plot(probabilities, one_positive, color="#377eb8", linewidth=2.4)
    axes[0].axvline(one_critical, color="#d62728", linewidth=1.4, linestyle=":")
    axes[0].set_title("One accepted A is sufficient (n=16)")

    axes[1].plot(probabilities, np.zeros_like(probabilities), color="#1f1f1f", linewidth=2.2, label="stable")
    axes[1].plot(probabilities, two_low, color="#777777", linewidth=1.8, linestyle="--", label="unstable")
    axes[1].plot(probabilities, two_high, color="#ff8c00", linewidth=2.4)
    axes[1].scatter([two_critical_probability], [two_critical_x], color="#d62728", s=28, zorder=3)
    axes[1].axvline(two_critical_probability, color="#d62728", linewidth=1.4, linestyle=":")
    axes[1].set_title("Two accepted A samples required (n=128)")

    for axis in axes:
        for dose in DOSES[1:]:
            axis.axvline(dose, color="#bbbbbb", linewidth=0.7, alpha=0.6)
        axis.set_xlim(0.0, 0.12)
        axis.set_ylim(-0.025, 1.025)
        axis.set_xlabel("conditional verifier acceptance p")
        axis.grid(alpha=0.2, linestyle="--")
    axes[0].set_ylabel("fixed-point A prevalence")
    axes[1].legend(loc="center right", frameon=False)
    figure.suptitle("Idealized iterative-SFT phase map", fontsize=13, y=0.98)

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(output)
    figure.savefig(output, bbox_inches="tight", metadata={"Date": None})
    lines = output.read_text(encoding="utf-8").splitlines()
    output.write_text("\n".join(line.rstrip() for line in lines) + "\n", encoding="utf-8")
    plt.close(figure)


def main() -> None:
    args = parse_args()
    if args.output_json.resolve() == args.output_svg.resolve():
        raise ValueError("JSON and SVG outputs must differ")
    for output in (args.output_json, args.output_svg):
        if output.exists():
            raise FileExistsError(output)

    two_hit_critical = two_hit_saddle(128)
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "analysis_id": "iterative_sft_verifier_phase_map",
        "model": {
            "state": "x_t = prevalence of answer-correct, strict-wrong behavior A",
            "recurrence": "x_(t+1) = P[Binomial(n, p*x_t) >= h]",
            "assumption": "one fixed-cardinality SFT round reproduces its selected-target mixture",
            "unmodeled_rounding": ["baseline A innovation", "imperfect SFT transfer", "finite rounds"],
        },
        "critical_points": {
            "one_hit_n16": {"probability": 1.0 / 16.0, "kind": "clean-state stability loss"},
            "one_hit_n128": {"probability": 1.0 / 128.0, "kind": "clean-state stability loss"},
            "two_hit_n128": {
                "probability": two_hit_critical[0],
                "x": two_hit_critical[1],
                "kind": "saddle-node with clean/high coexistence",
            },
        },
        "dose_predictions": {
            "one_hit_n16": {str(probability): one_hit_fixed_points(16, probability) for probability in DOSES},
            "one_hit_n128": {str(probability): one_hit_fixed_points(128, probability) for probability in DOSES},
            "two_hit_n128": {
                str(probability): two_hit_fixed_points(128, probability, two_hit_critical) for probability in DOSES
            },
        },
        "claim_scope": {
            "theory_prediction_only": True,
            "applies_to_current_rl_runs": False,
            "phase_transition_observed": False,
        },
    }
    result["implementation"] = {
        "path": str(Path(__file__).resolve()),
        "size_bytes": Path(__file__).stat().st_size,
        "sha256": file_sha256(Path(__file__)),
    }
    result["content_sha256"] = canonical_json_sha256(result)

    write_figure(args.output_svg, two_hit_critical)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output_json": str(args.output_json.resolve()),
                "output_svg": str(args.output_svg.resolve()),
                "content_sha256": result["content_sha256"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
